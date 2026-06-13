import logging

from fastapi import Depends, APIRouter, HTTPException
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from typing import  Annotated, Optional

from tasks import update_location_task
from schemas.general import GPSInfo
from auth import _require_owner
from auth.auth_models import auth_dependency
from auth.devices import verify_device_and_user
from auth.types import AccessLevel
from database import get_session
from schemas import CamelCaseModel

from location.gps_pipeline import run_pipeline
from database.models import Image, RawGPS, ImageGPS, SensorDevice
from datetime import datetime, timezone as py_timezone
from sqlalchemy import update as sa_update
from integrations.sessions.redis import redis_client as _redis_client
from timezonefinder import TimezoneFinder

from location.utils import find_timezone

router = APIRouter()
logger = logging.getLogger(__name__)

@router.get("/health")
def health_check():
    return {"status": "ok"}

class GPSUploadRequest(CamelCaseModel):
    latitude: float
    longitude: float
    elevation: Optional[float] = None
    timestamp: str
    device_id: str

tf = TimezoneFinder()
_GPS_PIPELINE_GATE_MINUTES = 15

@router.put("/upload-gps", summary="Ingest a GPS reading from a device")
async def upload_gps(
    request: GPSUploadRequest,
    session: Session = Depends(get_session)
):
    # find device
    device_id = request.device_id
    user = verify_device_and_user(session, device_id, "location")

    session.execute(
        sa_update(SensorDevice)
        .where(SensorDevice.device_id == device_id, SensorDevice.sensor_type == "location")
        .values(last_seen=datetime.now(py_timezone.utc))
    )

    timezone = find_timezone(request.longitude, request.latitude)
    timestamp = datetime.fromisoformat(request.timestamp).astimezone(py_timezone.utc).replace(tzinfo=None)

    stmt = insert(RawGPS).values(
        device_id=user.id,
        latitude=request.latitude,
        longitude=request.longitude,
        elevation=request.elevation,
        timestamp=timestamp,
        timezone=timezone
    )

    logger.debug(
        "GPS upsert device=%s lat=%s lon=%s elev=%s time=%s tz=%s",
        device_id, request.latitude, request.longitude, request.elevation, timestamp, timezone,
    )

    stmt = stmt.on_conflict_do_update(
        constraint="uq_raw_gps_device_time",
        set_={
            "latitude": request.latitude,
            "longitude": request.longitude,
            "elevation": request.elevation,
            "timezone": timezone
        }
    )

    stmt = stmt.returning(RawGPS.id)
    result = session.execute(stmt)
    session.commit()

    # Trigger GPS pipeline (→ location enrichment → segmentation) at most every
    # _GPS_PIPELINE_GATE_MINUTES minutes per device.  The gate lives in Redis so
    # it's shared across API workers and survives restarts within the TTL window.
    gate_key = f"gps_pipeline_gate:{user.device_id}"
    if not _redis_client.get_value(gate_key):
        _redis_client.set_with_ttl(gate_key, "1", _GPS_PIPELINE_GATE_MINUTES * 60)
        date = timestamp.strftime("%Y-%m-%d")
        logger.debug("Triggering GPS pipeline for device %s and date %s", user.device_id, date)
        update_location_task.delay(user.device_id, date)
    else:
        logger.debug("GPS pipeline gate active for device %s, skipping trigger", user.device_id)
        logger.debug("Gate TTL remaining: %s seconds", _redis_client.get_ttl(gate_key))

    return {"status": "success", "raw_gps_id": result.scalar()}


@router.get("/process-gps", summary="Run the GPS stop/segment pipeline for a date")
async def process_gps(
    device: str,
    date: str,
    access_level: Annotated[AccessLevel, Depends(auth_dependency)] = AccessLevel.NONE,
    session: Session = Depends(get_session),
):
    _require_owner(access_level)
    if date == "all":
        dates = session.execute(select(Image.date).where(Image.device == device, Image.timezone == None).distinct()).scalars().all()
        for d in dates:
            if d: run_pipeline(session, device, d)
    else:
        run_pipeline(session, device, date)


@router.get("/latest-gps", summary="Get the most recent GPS fix for a device")
async def last_gps(
    device: str,
    session: Session = Depends(get_session)
):
    associated_user = session.execute(select(SensorDevice.associated_user).where(SensorDevice.device_id == device)).scalars().first()
    if not associated_user:
        logger.warning("No associated user found for device %s", device)
        raise HTTPException(status_code=404, detail="Device not found or not associated with a user")

    last_gps = session.execute(select(RawGPS).where(RawGPS.device_id == associated_user).order_by(RawGPS.timestamp.desc()).limit(1)).scalars().first()
    if not last_gps:
        raise HTTPException(status_code=404, detail="No GPS data found for device")
    logger.debug(
        "Last GPS device=%s lat=%s lon=%s time=%s tz=%s",
        device, last_gps.latitude, last_gps.longitude, last_gps.timestamp, last_gps.timezone,
    )
    return {
        "latitude": last_gps.latitude,
        "longitude": last_gps.longitude,
        "elevation": last_gps.elevation,
        "timestamp": last_gps.timestamp.isoformat(),
        "timezone": last_gps.timezone
    }

_GPS_TRACK_CACHE_TTL_TODAY = 60
_GPS_TRACK_CACHE_TTL_PAST = 600
# v2 adds rawGps + timestamps — bump the key so old list-format entries aren't served
_GPS_CACHE_KEY = "gps_track_v2:{device}:{date}"


def _to_gps_info(lat: float, lon: float, elev, ts_ms: float | None) -> dict:
    return {
        "latitude": lat,
        "longitude": lon,
        "elevation": elev,
        "timestamp": ts_ms,
    }


@router.get("/get-gps-by-date", summary="Get the GPS track for a device and date")
def get_gps_by_date(
    date: str,
    device: str,
    access_level: Annotated[AccessLevel, Depends(auth_dependency)] = AccessLevel.NONE,
    session: Session = Depends(get_session),
    nested=False,
):
    _require_owner(access_level)
    if not date:
        raise HTTPException(status_code=400, detail="Date parameter is required")

    from datetime import date as _date_cls
    from sqlalchemy import func as _func
    is_today = (date == _date_cls.today().isoformat())
    cache_key = _GPS_CACHE_KEY.format(device=device, date=date)

    if not nested:
        cached = _redis_client.get_json(cache_key)
        if cached is not None:
            return cached

    # ── Image GPS (sparse — one point per image) ─────────────────────────────
    image_gps_rows = session.execute(
        select(ImageGPS)
        .join(Image, Image.id == ImageGPS.image_id)
        .where(Image.date == date, Image.deleted == False, Image.device == device)
        .order_by(Image.timestamp.asc())
    ).scalars().all()

    image_gps = [
        _to_gps_info(g.latitude, g.longitude, g.elevation,
                     g.timestamp * 1000 if g.timestamp is not None else None)
        for g in image_gps_rows
        if g.latitude is not None and g.longitude is not None
    ]

    # Trigger GPS pipeline when there are no image GPS points yet (existing behavior)
    if not image_gps and not nested:
        run_pipeline(session, device, date)
        return get_gps_by_date(date, device, access_level, session, nested=True)

    # ── Raw GPS (dense — from standalone GPS device/phone) ───────────────────
    from database.models import Device as DeviceModel
    from datetime import timezone as _tz
    raw_gps_rows = session.execute(
        select(RawGPS)
        .join(DeviceModel, DeviceModel.id == RawGPS.device_id)
        .where(DeviceModel.device_id == device)
        .where(_func.date(RawGPS.timestamp) == date)
        .order_by(RawGPS.timestamp.asc())
    ).scalars().all()

    raw_gps = [
        _to_gps_info(
            g.latitude, g.longitude, g.elevation,
            g.timestamp.replace(tzinfo=_tz.utc).timestamp() * 1000
            if g.timestamp is not None else None,
        )
        for g in raw_gps_rows
        if g.latitude is not None and g.longitude is not None
    ]

    result = {"rawGps": raw_gps, "imageGps": image_gps}

    if not nested:
        ttl = _GPS_TRACK_CACHE_TTL_TODAY if is_today else _GPS_TRACK_CACHE_TTL_PAST
        _redis_client.set_json_with_ttl(cache_key, result, ttl)

    return result

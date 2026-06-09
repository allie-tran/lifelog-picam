import logging

from fastapi import Depends, FastAPI, HTTPException
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from typing import  Annotated, Optional

from app_types.general import GPSInfo
from auth import _require_owner
from auth.auth_models import auth_dependency
from auth.devices import verify_device_and_user
from auth.types import AccessLevel
from database import get_session
from app_types import CamelCaseModel

from location.gps_pipeline import run_pipeline
from database.models import Image, RawGPS, ImageGPS, SensorDevice
from datetime import datetime, timezone as py_timezone
from sqlalchemy import update as sa_update
from sessions.redis import redis_client as _redis_client
from timezonefinder import TimezoneFinder

from location.utils import find_timezone

app = FastAPI()
logger = logging.getLogger(__name__)

@app.get("/health")
def health_check():
    return {"status": "ok"}

class GPSUploadRequest(CamelCaseModel):
    latitude: float
    longitude: float
    elevation: Optional[float] = None
    timestamp: str
    device_id: str

tf = TimezoneFinder()
_GPS_PIPELINE_GATE_MINUTES = 10

@app.put("/upload-gps")
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
        from tasks import run_gps_pipeline_task
        run_gps_pipeline_task.delay(user.device_id, date)

    return {"status": "success", "raw_gps_id": result.scalar()}


@app.get("/process-gps")
async def process_gps(
    device: str,
    date: str,
    session: Session = Depends(get_session)
):
    if date == "all":
        # run all
        dates = session.execute(select(Image.date).where(Image.device == device, Image.timezone == None).distinct()).scalars().all()
        for date in dates:
            run_pipeline(session, device, date)
    else:
        run_pipeline(session, device, date)


@app.get("/latest-gps")
async def last_gps(
    device: str,
    session: Session = Depends(get_session)
):
    associated_user = session.execute(select(SensorDevice.associated_user).where(SensorDevice.device_id == device)).scalars().first()
    if not associated_user:
        logger.warning("No associated user found for device %s", device)
        raise HTTPException(status_code=404, detail="Device not found or not associated with a user")

    last_gps = session.execute(select(RawGPS).where(RawGPS.device_id == associated_user).order_by(RawGPS.timestamp.desc())).scalars().first()
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

@app.get("/get-gps-by-date")
def get_gps_by_date(
    date: str,
    device: str,
    access_level: Annotated[AccessLevel, Depends(auth_dependency)] = AccessLevel.NONE,
    session: Session = Depends(get_session),
    nested=False,
):
    _require_owner(access_level)

    from datetime import date as _date_cls
    is_today = (date == _date_cls.today().isoformat())

    if not nested:
        cached = _redis_client.get_json(f"gps_track:{device}:{date}")
        if cached is not None:
            return cached

    gps = session.execute(
        select(ImageGPS)
        .where(Image.date == date)
        .where(Image.deleted == False)
        .where(Image.device == device)
        .join(Image, Image.id == ImageGPS.image_id)
        .order_by(Image.timestamp.desc())
    ).scalars().all()

    res = [GPSInfo.model_validate(g.__dict__) for g in gps]
    if len(res) == 0 and not nested and date:
        run_pipeline(session, device, date)
        return get_gps_by_date(date, device, access_level, session, nested=True)

    if not nested and res:
        ttl = _GPS_TRACK_CACHE_TTL_TODAY if is_today else _GPS_TRACK_CACHE_TTL_PAST
        _redis_client.set_json_with_ttl(
            f"gps_track:{device}:{date}",
            [r.model_dump(mode="json") for r in res],
            ttl,
        )
    return res

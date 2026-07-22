import logging
import uuid

from fastapi import Depends, APIRouter, HTTPException
from sqlalchemy import select, func, delete
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from typing import  Annotated, List, Optional

from tasks import update_location_task
from schemas.general import Coordinate, GPSInfo
from auth import _require_owner, _require_any_access
from auth.auth_models import auth_dependency, get_user
from auth.devices import verify_device_and_user
from auth.types import AccessLevel
from database import get_session
from schemas import CamelCaseModel

from location.gps_pipeline import run_pipeline
from database.models import Image, RawGPS, ImageGPS, SensorDevice, Location, LocationLabel
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
    # Optional android.location.Location fix-quality signal — older uploads omit these.
    accuracy: Optional[float] = None
    vertical_accuracy: Optional[float] = None
    speed: Optional[float] = None
    speed_accuracy: Optional[float] = None
    bearing: Optional[float] = None
    provider: Optional[str] = None

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
        timezone=timezone,
        accuracy=request.accuracy,
        vertical_accuracy=request.vertical_accuracy,
        speed=request.speed,
        speed_accuracy=request.speed_accuracy,
        bearing=request.bearing,
        provider=request.provider,
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
            "timezone": timezone,
            "accuracy": request.accuracy,
            "vertical_accuracy": request.vertical_accuracy,
            "speed": request.speed,
            "speed_accuracy": request.speed_accuracy,
            "bearing": request.bearing,
            "provider": request.provider,
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
    # access_level: Annotated[AccessLevel, Depends(auth_dependency)] = AccessLevel.NONE,
    session: Session = Depends(get_session),
):
    # _require_owner(access_level)
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


# ---------------------------------------------------------------------------
# Labeled locations (per-user — Home / Work / custom, stored in location_labels)
# ---------------------------------------------------------------------------

class LabeledLocationOut(CamelCaseModel):
    location_id: str
    label: str
    label_kind: str
    name: Optional[str] = None
    latitude: Coordinate = None
    longitude: Coordinate = None
    address: Optional[str] = None


class LabelRequest(CamelCaseModel):
    location_id: Optional[str] = None   # existing detected stop; None => manual pin
    label: str
    label_kind: str = "other"           # home / work / other
    name: Optional[str] = None          # required for a manual pin
    latitude: Coordinate = None    # required for a manual pin
    longitude: Coordinate = None


def _bust_location_caches() -> None:
    # Location names surface in cached day-nav + day browse payloads; relabeling
    # is rare, so a broad bust is fine — the next read recomputes.
    _redis_client.delete_pattern("day-nav:*")
    _redis_client.delete_pattern("browse:day:*")


@router.get("/labeled", summary="Get the user's labeled locations", response_model=List[LabeledLocationOut])
def get_labeled_locations(
    user=Depends(get_user),
    access_level: Annotated[AccessLevel, Depends(auth_dependency)] = AccessLevel.NONE,
    session: Session = Depends(get_session),
):
    _require_any_access(access_level)
    rows = session.execute(
        select(
            LocationLabel.location_id,
            LocationLabel.label,
            LocationLabel.label_kind,
            Location.name,
            Location.address,
            Location.latitude,
            Location.longitude,
        )
        .join(Location, Location.id == LocationLabel.location_id)
        .where(LocationLabel.username == user.username)
    ).all()
    return [
        LabeledLocationOut(
            location_id=str(lid),
            label=label,
            label_kind=kind,
            name=name,
            address=address,
            latitude=lat,
            longitude=lon,
        )
        for lid, label, kind, name, address, lat, lon in rows
    ]


@router.put("/label", summary="Set/replace a user's label for a location")
def upsert_label(
    req: LabelRequest,
    user=Depends(get_user),
    access_level: Annotated[AccessLevel, Depends(auth_dependency)] = AccessLevel.NONE,
    session: Session = Depends(get_session),
):
    _require_owner(access_level)

    if req.location_id:
        location_id = uuid.UUID(req.location_id)
        if session.get(Location, location_id) is None:
            raise HTTPException(status_code=404, detail="Location not found")
    else:
        # Manual pin — create (or reuse) a stop Location row for these coords.
        if req.latitude is None or req.longitude is None:
            raise HTTPException(status_code=400, detail="latitude/longitude required for a manual pin")
        key = f"stop=True,manual_{req.latitude:.5f}_{req.longitude:.5f}"
        name = req.name or "Custom place"
        tz = find_timezone(req.longitude, req.latitude)
        loc_stmt = (
            insert(Location)
            .values(
                id=uuid.uuid4(),
                key=key,
                name=name,
                stop=True,
                latitude=req.latitude,
                longitude=req.longitude,
                timezone=tz,
            )
            .on_conflict_do_update(index_elements=["key"], set_={"name": name})
            .returning(Location.id)
        )
        location_id = session.execute(loc_stmt).scalar_one()

    label_stmt = (
        insert(LocationLabel)
        .values(
            id=uuid.uuid4(),
            username=user.username,
            location_id=location_id,
            label=req.label,
            label_kind=req.label_kind,
        )
        .on_conflict_do_update(
            constraint="uq_location_label_user_loc",
            set_={"label": req.label, "label_kind": req.label_kind},
        )
    )
    session.execute(label_stmt)
    session.commit()
    _bust_location_caches()
    return {"success": True, "locationId": str(location_id)}


@router.delete("/label", summary="Remove a user's label from a location")
def delete_label(
    location_id: str,
    user=Depends(get_user),
    access_level: Annotated[AccessLevel, Depends(auth_dependency)] = AccessLevel.NONE,
    session: Session = Depends(get_session),
):
    _require_owner(access_level)
    session.execute(
        delete(LocationLabel).where(
            LocationLabel.username == user.username,
            LocationLabel.location_id == uuid.UUID(location_id),
        )
    )
    session.commit()
    _bust_location_caches()
    return {"success": True}


class StopOption(CamelCaseModel):
    location_id: str
    name: str
    address: Optional[str] = None
    latitude: Coordinate
    longitude: Coordinate
    count: int
    label: Optional[str] = None
    label_kind: Optional[str] = None


@router.get("/stops", summary="List detected stop locations for a device", response_model=List[StopOption])
def list_stops(
    device: str,
    user=Depends(get_user),
    access_level: Annotated[AccessLevel, Depends(auth_dependency)] = AccessLevel.NONE,
    session: Session = Depends(get_session),
):
    _require_any_access(access_level)
    rows = session.execute(
        select(
            Location.id,
            Location.name,
            Location.address,
            Location.latitude,
            Location.longitude,
            func.count(Image.id),
            LocationLabel.label,
            LocationLabel.label_kind,
        )
        .join(Image, Image.location_id == Location.id)
        .outerjoin(
            LocationLabel,
            (LocationLabel.location_id == Location.id)
            & (LocationLabel.username == user.username),
        )
        .where(
            Image.device == device,
            Image.deleted == False,
            Location.stop == True,
            Location.latitude.isnot(None),
            Location.longitude.isnot(None),
        )
        .group_by(Location.id, LocationLabel.label, LocationLabel.label_kind)
        .order_by(func.count(Image.id).desc())
    ).all()

    stops: list[StopOption] = []
    for lid, name, address, lat, lon, count, label, label_kind in rows:
        display = name if name and name not in ("---", "Unknown Place", "") else (address or "")
        if not display:
            continue
        stops.append(StopOption(
            location_id=str(lid),
            name=display,
            address=address,
            latitude=lat,
            longitude=lon,
            count=count,
            label=label,
            label_kind=label_kind,
        ))
    return stops

import logging
from datetime import datetime, timedelta, timezone
from typing import Annotated, List, Optional

from fastapi import Depends, FastAPI
from sqlalchemy import select
from sqlalchemy.orm import Session

from app_types.general import LocationInfo
from auth import _require_any_access
from auth.auth_models import auth_dependency
from auth.types import AccessLevel
from database import get_session
from database.models import Device, Image, Location, RawGPS, SensorDevice
from dependencies import CamelCaseModel
from sessions.redis import redis_client

app = FastAPI()
logger = logging.getLogger(__name__)

_CAMERA_ONLINE_MINUTES = 15
_SENSOR_ONLINE_MINUTES = 30
_GPS_STALE_MINUTES = 60


class SensorStatus(CamelCaseModel):
    device_id: str
    sensor_type: str
    nickname: Optional[str] = None
    last_seen: Optional[datetime] = None
    online: bool = False


class CurrentStatusResponse(CamelCaseModel):
    camera_last_seen: Optional[datetime] = None
    camera_online: bool = False
    current_activity: Optional[str] = None
    current_activity_description: Optional[str] = None
    current_location: Optional[LocationInfo] = None
    current_thumbnail: Optional[str] = None
    segment_since: Optional[datetime] = None
    current_lat: Optional[float] = None
    current_lon: Optional[float] = None
    sensors: List[SensorStatus] = []
    summary: Optional[str] = None
    summary_updated_at: Optional[datetime] = None


@app.get("/health")
def health_check():
    return {"status": "ok"}


@app.get("/current", response_model=CurrentStatusResponse)
def get_current_status(
    device: str,
    session: Session = Depends(get_session),
    access_level: Annotated[AccessLevel, Depends(auth_dependency)] = AccessLevel.NONE,
):
    _require_any_access(access_level)

    now = datetime.now(timezone.utc)

    content_device = session.execute(
        select(Device).where(Device.device_id == device)
    ).scalar_one_or_none()

    if not content_device:
        return CurrentStatusResponse()


    sensors_rows = session.execute(
        select(SensorDevice).where(SensorDevice.associated_user == content_device.id)
    ).scalars().all()

    sensors: List[SensorStatus] = []
    camera_last_seen = None
    camera_online = False
    for s in sensors_rows:
        s_last_seen = s.last_seen
        s_online = (
            s_last_seen is not None
            and (now - s_last_seen).total_seconds() < _SENSOR_ONLINE_MINUTES * 60
        )
        sensors.append(SensorStatus(
            device_id=str(s.device_id),
            sensor_type=str(s.sensor_type),
            nickname=str(s.device_nickname),
            last_seen=s_last_seen,  # type: ignore
            online=s_online,
        ))
        if str(s.sensor_type) == "camera":
            camera_last_seen                = max(camera_last_seen, s_last_seen) if camera_last_seen else s_last_seen  # type: ignore
            camera_online = camera_online or s_online

    latest_image = session.execute(
        select(Image)
        .where(Image.device == device, Image.deleted == False)
        .order_by(Image.timestamp.desc())
        .limit(1)
    ).scalar_one_or_none()

    current_activity = None
    current_activity_description = None
    current_thumbnail = None
    segment_since = None
    current_location: Optional[LocationInfo] = None

    if latest_image:
        current_activity = latest_image.activity or None
        current_activity_description = latest_image.activity_description or None
        current_thumbnail = latest_image.thumbnail

        if latest_image.segment_id is not None:
            seg_start = session.execute(
                select(Image.timestamp)
                .where(
                    Image.device == device,
                    Image.segment_id == latest_image.segment_id,
                    Image.date == latest_image.date,
                    Image.deleted == False,
                )
                .order_by(Image.timestamp.asc())
                .limit(1)
            ).scalar_one_or_none()
            segment_since = seg_start

        if latest_image.location_id is not None:
            loc_row = session.execute(
                select(Location).where(Location.id == latest_image.location_id)
            ).scalar_one_or_none()
            if loc_row:
                try:
                    current_location = LocationInfo.model_validate(loc_row.__dict__)
                except Exception:
                    pass

    latest_gps = session.execute(
        select(RawGPS)
        .where(RawGPS.device_id == content_device.id)
        .order_by(RawGPS.timestamp.desc())
        .limit(1)
    ).scalar_one_or_none()

    current_lat = None
    current_lon = None
    if latest_gps:
        age_min = (now - latest_gps.timestamp.replace(tzinfo=timezone.utc)).total_seconds() / 60
        if age_min < _GPS_STALE_MINUTES:
            current_lat = latest_gps.latitude
            current_lon = latest_gps.longitude

    cache_key = f"status:{device}:summary"
    cache_data = redis_client.get_json(cache_key)
    summary_text: Optional[str] = None
    summary_updated_at: Optional[datetime] = None
    if cache_data:
        summary_text = cache_data.get("text")
        raw_ts = cache_data.get("updated_at")
        if raw_ts:
            try:
                summary_updated_at = datetime.fromisoformat(raw_ts)
            except ValueError:
                pass

    return CurrentStatusResponse(
        camera_last_seen=camera_last_seen,  # type: ignore
        camera_online=camera_online,
        current_activity=current_activity,  # type: ignore
        current_activity_description=current_activity_description,  # type: ignore
        current_location=current_location,
        current_thumbnail=current_thumbnail,  # type: ignore
        segment_since=segment_since,
        current_lat=current_lat,  # type: ignore
        current_lon=current_lon,  # type: ignore
        sensors=sensors,
        summary=summary_text,
        summary_updated_at=summary_updated_at,
    )

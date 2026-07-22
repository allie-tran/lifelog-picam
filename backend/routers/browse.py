import logging
import os
from typing import Annotated, Any, List, Literal, Optional
from fastapi import Depends, APIRouter, HTTPException, Query
from fastapi.encoders import jsonable_encoder
from collections import Counter
from sqlalchemy import asc, update
from sqlalchemy.orm import Session, selectinload
from datetime import datetime, timedelta, timezone

from sqlalchemy.sql import func, select

from schemas.general import Coordinate, GPSInfo, GridImage, LifelogImage, LocationInfo, ResultSegment
from auth import _require_owner, _require_any_access
from auth.auth_models import auth_dependency, get_user
from auth.types import AccessLevel
from core.config import DIR
from database import get_session
from database.models import HeartRateData as HeartRateTable, Image, ImageGPS, ImagePerson, Location, MagnetometerData as MagnetometerTable, AccelerometerData as AccelerometerTable, GyroscopeData as GyroscopeTable, PPGData as PPGTable, PPIData as PPITable
from database.types import ImageRecord, _orm_to_lifelog, _orm_to_grid
from core.dependencies import CamelCaseModel
from pipelines.all import process_image
from services.anonymise import anonymise_image
from services.segmentation import load_all_segments
from services.utils import get_thumbnail_path
from integrations.sessions.redis import redis_client

from tasks import anonymise_image_task

logger = logging.getLogger(__name__)
router = APIRouter()

_SEG_COMPLETE_TTL = 3600 * 10  # seconds to cache "all images segmented" per device/date
_BROWSE_CACHE_TTL_TODAY = 60
_BROWSE_CACHE_TTL_PAST = 600


def _maybe_load_segments(session: Session, device: str, date: str) -> None:
    """
    For past dates: run segmentation as a fallback if GPS pipeline never ran.
    For today: skip — segmentation is driven by the GPS pipeline triggered from
    upload_gps, so pre-segmenting here would block the location-aware re-run.
    """
    from datetime import date as _date_cls
    if date == _date_cls.today().isoformat():
        return  # GPS pipeline handles today

    cache_key = f"segs_complete:{device}:{date}"
    if redis_client.get_value(cache_key):
        return  # recently verified: all segmented

    load_all_segments(session, device, date, skip_annotations=True)

    # Check if any unsegmented remain; if not, cache the result
    remaining = session.execute(
        select(func.count(Image.id)).where(
            Image.device == device,
            Image.date == date,
            Image.segment_id.is_(None),
            Image.deleted == False,
        )
    ).scalar_one()
    if remaining == 0:
        redis_client.set_with_ttl(cache_key, "1", _SEG_COMPLETE_TTL)

@router.get("/health")
def health_check():
    return {"status": "ok"}

@router.get("/list-biometrics-sensors")
def list_sensors():
    return ["1ABA333D"]

class MeasurementData(CamelCaseModel):
    time_stamp: int
    value: float

class NestedMeasurementData(CamelCaseModel):
    time_stamp: int
    values: dict[str, float | None]

class LogResponse(CamelCaseModel):
    keys: list[str]
    logs: dict[str, list[NestedMeasurementData]]

class RangeRequest(CamelCaseModel):
    date: str
    start_time: int
    end_time: int

ITEMS_PER_PAGE = 20

old_epoch_year = datetime.timestamp(datetime(1970, 1, 1))
epoch_year = datetime.timestamp(datetime(2000, 1, 1))
timedelta_seconds = epoch_year - old_epoch_year

def calculate_magnitude(x, y, z):
    return round((x**2 + y**2 + z**2) ** 0.5, 4)

def get_attr(obj, attr):
    if attr == "magnitude":
        return calculate_magnitude(getattr(obj, "x"), getattr(obj, "y"), getattr(obj, "z"))
    if "." in attr:
        name, index = attr.split(".")
        return getattr(obj, name)[int(index)]
    else:
        return getattr(obj, attr)

def _mark_images_not_new(session: Session, image_paths: list[str], device: str):
    if not image_paths:
        return
    session.execute(
        update(Image)
        .where(Image.image_path.in_(image_paths))
        .where(Image.device == device)
        .values(new=False)
    )
    session.flush()


@router.get("/logs/{sensor}")
def get_sensor_logs(
    sensor: Literal["heartrate", "magnetometer", "accelerometer", "gyroscope", "ppg", "ppi"],
    date: str,
    device_id: str,
    sample_rate: int = Query(default=50, description="Return every N-th row. Higher = fewer points."),
    session: Session = Depends(get_session)
) -> LogResponse:

    date_value = datetime.strptime(date, "%Y-%m-%d")
    start_timestamp = date_value.timestamp() - timedelta_seconds
    end_timestamp = start_timestamp + 86400

    start_ns = int(start_timestamp * 1_000_000_000)
    end_ns = int(end_timestamp * 1_000_000_000)

    # check if there is **any** heartrate data for the given date and device_id
    hr_exists = session.query(HeartRateTable).filter(
        HeartRateTable.device_id == device_id,
        HeartRateTable.time_stamp >= start_ns,
        HeartRateTable.time_stamp < end_ns
    ).first()
    if not hr_exists:
        return LogResponse(keys=[], logs={})

    # 1. Define the full registry of targets
    sensor_registry = {
        "heartrate": (HeartRateTable, ["hr"]),
        "ppi": (PPITable, ["hr", "ppi"]),
        "magnetometer": (MagnetometerTable, ["x", "y", "z", "magnitude"]),
        "accelerometer": (AccelerometerTable, ["x", "y", "z", "magnitude"]),
        "gyroscope": (GyroscopeTable, ["x", "y", "z", "magnitude"]),
        "ppg": (PPGTable, ["channel_samples.0", "channel_samples.1", "channel_samples.2", "channel_samples.3"]),
    }

    sensor_registry = {sensor: sensor_registry[sensor]}
    targets = [(name, table, keys) for name, (table, keys) in sensor_registry.items()]

    all_res = {}

    for name, table, keys in targets:
        # 3. Create a window function to number the rows sequentially
        row_num_col = func.row_number().over(order_by=table.time_stamp).label("row_num")

        # 4. Core query wrapping our filter constraints
        base_stmt = (
            select(table, row_num_col)
            .where(
                table.device_id == device_id,
                table.time_stamp >= start_ns,
                table.time_stamp <= end_ns
            )
        ).subquery()

        # 5. Filter inside Postgres using Modulo (%) to sample every Nth row
        if name in ["heartrate", "ppi"]:
            # For heart rate, we want to sample every row
            sampled_stmt = select(base_stmt)
        else:
            sampled_stmt = select(base_stmt).where(base_stmt.c.row_num % sample_rate == 0)

        res = session.execute(sampled_stmt).all()

        # Define a strict 60-second interval (5,000,000,000 nanoseconds)
        BUCKET_SIZE_NS = 5 * 1_000_000_000

        # 6. Group existing rows into their respective 5s buckets using integer division
        # This runs in O(M) time where M is just the small dataset returned by Postgres
        bucketed_data = {}
        for row in res:
            # Snap the row's timestamp down to the nearest 5-second bucket start
            bucket_id = (row.time_stamp // BUCKET_SIZE_NS) * BUCKET_SIZE_NS
            bucketed_data[bucket_id] = row

        # 7. Generate the uniform timeline from start to end by steps of 5 seconds
        all_res[name] = []

        this_start_ns = max(start_ns, min(bucketed_data.keys()) if bucketed_data else start_ns)
        this_end_ns = min(end_ns, max(bucketed_data.keys()) + BUCKET_SIZE_NS if bucketed_data else end_ns)

        for current_ts_ns in range(this_start_ns, this_end_ns, BUCKET_SIZE_NS):
            frontend_timestamp = int(current_ts_ns // 1_000_000_000 + timedelta_seconds)

            # O(1) instant hash lookup
            if current_ts_ns in bucketed_data:
                row = bucketed_data[current_ts_ns]
                data: dict[str, Any] = {k: get_attr(row, k) for k in keys}
                all_res[name].append(NestedMeasurementData(
                    time_stamp=frontend_timestamp,
                    values=data
                ))
            else:
                # Drop the null object for gaps
                all_res[name].append(NestedMeasurementData(
                    time_stamp=frontend_timestamp,
                    values={k: None for k in keys}
                ))

    return LogResponse(keys=list(all_res.keys()), logs=all_res)

def _modal_by_segment(rows) -> dict[int, str]:
    """Collapse (segment_id, value) rows into {segment_id: modal value}, skipping falsy values."""
    by_seg: dict[int, list[str]] = {}
    for seg_id, value in rows:
        if value:
            by_seg.setdefault(seg_id, []).append(value)
    return {sid: Counter(vs).most_common(1)[0][0] for sid, vs in by_seg.items()}


def _fetch_segment_modes(session, device: str, date: str) -> dict[int, str]:
    """{segment_id: modal transport mode} from ImageGPS.mode."""
    rows = session.execute(
        select(Image.segment_id, ImageGPS.mode)
        .join(ImageGPS, ImageGPS.image_id == Image.id)
        .where(
            Image.device == device,
            Image.date == date,
            Image.deleted == False,
            Image.segment_id.isnot(None),
            ImageGPS.mode.isnot(None),
        )
    ).all()
    return _modal_by_segment(rows)


def _fetch_segment_label_kinds(session, device: str, date: str, username: str | None = None) -> dict[int, str]:
    """{segment_id: modal user label_kind (home/work/other)} for the segment's location."""
    from database.models import LocationLabel
    rows = session.execute(
        select(Image.segment_id, LocationLabel.label_kind)
        .join(Location, Image.location_id == Location.id)
        .join(
            LocationLabel,
            (LocationLabel.location_id == Location.id)
            & (LocationLabel.username == username),
        )
        .where(
            Image.device == device,
            Image.date == date,
            Image.deleted == False,
            Image.segment_id.isnot(None),
        )
    ).all()
    return _modal_by_segment(rows)


@router.get("/day-nav")
async def get_day_nav(
    device: str,
    date: str,
    user=Depends(get_user),
    access_level: Annotated[AccessLevel, Depends(auth_dependency)] = AccessLevel.NONE,
    session: Session = Depends(get_session),
):
    """Lightweight segment metadata for DayNavBar — no LLM, no day-summary dependency."""
    _require_owner(access_level)

    cache_key = f"day-nav:v3:{device}:{date}"
    cached = redis_client.get_json(cache_key)
    if cached is not None:
        return cached

    from services.summary import _fetch_segment_locations

    rows = session.execute(
        select(
            Image.segment_id,
            func.min(Image.timestamp).label("start_time"),
            func.max(Image.timestamp).label("end_time"),
            func.min(Image.activity).label("activity"),
            func.min(Image.activity_group).label("activity_group"),
            func.min(Image.timezone).label("timezone"),
        )
        .where(
            Image.device == device,
            Image.date == date,
            Image.deleted == False,
            Image.segment_id.isnot(None),
        )
        .group_by(Image.segment_id)
        .order_by(func.min(Image.timestamp).asc())
    ).all()

    if not rows:
        return []

    seg_to_location = _fetch_segment_locations(session, device, date, username=user.username)
    seg_mode = _fetch_segment_modes(session, device, date)
    seg_label_kind = _fetch_segment_label_kinds(session, device, date, username=user.username)

    segments = []
    for row in rows:
        start_ts = row.start_time
        end_ts = row.end_time
        duration = max(int((end_ts - start_ts).total_seconds()), 10) if start_ts and end_ts else 10
        loc = seg_to_location.get(row.segment_id)
        segments.append({
            "segmentId": row.segment_id,
            "startTime": start_ts.isoformat() if start_ts else None,
            "endTime": end_ts.isoformat() if end_ts else None,
            "timezone": row.timezone,
            "duration": duration,
            "activity": row.activity or "",
            "activityGroup": row.activity_group or "",
            "locationName": loc[0] if loc else None,
            "locationStop": loc[1] if loc else None,
            "mode": seg_mode.get(row.segment_id),
            "labelKind": seg_label_kind.get(row.segment_id),
        })

    today = datetime.now().strftime("%Y-%m-%d")
    ttl = _BROWSE_CACHE_TTL_TODAY if date == today else _BROWSE_CACHE_TTL_PAST
    redis_client.set_json_with_ttl(cache_key, segments, ttl)
    return segments


@router.get("/get-segments-by-date", response_model=dict)
async def get_segments_by_date(
    device: str,
    date: str = "",
    access_level: Annotated[AccessLevel, Depends(auth_dependency)] = AccessLevel.NONE,
    session: Session = Depends(get_session),
):
    _require_owner(access_level)

    if not date:
        date = datetime.now().strftime("%Y-%m-%d")

    _maybe_load_segments(session, device, date)

    cache_key = f"browse:day:{device}:{date}"
    cached = redis_client.get_json(cache_key)
    if cached is not None:
        return cached

    today = datetime.now().strftime("%Y-%m-%d")
    results = ImageRecord.find_segments(
        session,
        date=date,
        device=device,
        deleted=False,
        page=0,
        page_size=100_000,
        hour="",
        today=(date == today),
    )

    response = jsonable_encoder({
        "date": date,
        "segments": results["segments"],
    })

    ttl = _BROWSE_CACHE_TTL_TODAY if date == today else _BROWSE_CACHE_TTL_PAST
    redis_client.set_json_with_ttl(cache_key, response, ttl)
    return response


@router.get("/get-images-by-hour", response_model=dict)
async def get_images_by_hour(
    device: str,
    date: str = "",
    hour: str = "",
    access_level: Annotated[AccessLevel, Depends(auth_dependency)] = AccessLevel.NONE,
    session: Session = Depends(get_session),
):
    _require_owner(access_level)

    if not date:
        date = datetime.now().strftime("%Y-%m-%d")

    dir_path = f"{DIR}/{device}/{date}"
    if not os.path.exists(dir_path):
        return {"message": f"No images found for date {date}"}

    _maybe_load_segments(session, device, date)

    today = datetime.now().strftime("%Y-%m-%d")
    is_today = (date == today)

    # Resolve effective hour first (fast DISTINCT query, always fresh)
    all_hours = sorted(
        [h for h in ImageRecord.distinct(session, "hour", date=date, deleted=False, device=device) if h is not None],
        reverse=is_today,
    )
    effective_hour = hour or (all_hours[0] if all_hours else None)
    if not effective_hour:
        logger.info("No hours for date %s device %s", date, device)
        return {"date": date, "hour": None, "images": []}

    # Return cached response if available
    cache_key = f"browse:{device}:{date}:{effective_hour}"
    cached = redis_client.get_json(cache_key)
    if cached is not None:
        cached["available_hours"] = all_hours  # always serve fresh hour list
        return cached

    results = ImageRecord.find_segments(
        session,
        date=date,
        device=device,
        deleted=False,
        page=0,
        page_size=10_000,
        hour=effective_hour,
        today=is_today,
    )

    response = jsonable_encoder({
        "date": date,
        "hour": effective_hour,
        "segments": results["segments"],
        "available_hours": all_hours,
        "total_pages": results["total_pages"],
        "gps": results["gps"],
    })

    ttl = _BROWSE_CACHE_TTL_TODAY if is_today else _BROWSE_CACHE_TTL_PAST
    redis_client.set_json_with_ttl(cache_key, response, ttl)
    return response


@router.get("/get-images-by-segment", response_model=dict)
async def get_images_by_segment(
    device: str,
    date: str,
    segment_id: Optional[int] = Query(default=None),
    unsegmented: bool = False,
    access_level: Annotated[AccessLevel, Depends(auth_dependency)] = AccessLevel.NONE,
    session: Session = Depends(get_session),
):
    _require_owner(access_level)
    _maybe_load_segments(session, device, date)

    cache_key = f"browse:segment:{device}:{date}:{'unsegmented' if unsegmented else (segment_id if segment_id is not None else 'null')}"
    cached = redis_client.get_json(cache_key)
    if cached is not None:
        return cached

    stmt = (
        select(Image)
        .where(Image.date == date)
        .where(Image.device == device)
        .where(Image.deleted == False)
    )
    if unsegmented:
        stmt = stmt.where(Image.segment_id.is_(None))
    else:
        stmt = stmt.where(Image.segment_id == segment_id)
    stmt = stmt.order_by(asc(Image.timestamp))
    rows = session.execute(stmt).scalars().all()

    image_paths = [r.image_path for r in rows]
    path_to_location: dict[str, Location] = {}
    path_to_gps: dict[str, list[ImageGPS]] = {}

    if image_paths:
        for path, loc in session.execute(
            select(Image.image_path, Location)
            .join(Image.location)
            .where(Image.image_path.in_(image_paths))
        ).all():
            path_to_location[path] = loc

        for path, gps_row in session.execute(
            select(Image.image_path, ImageGPS)
            .join(ImageGPS.image)
            .where(Image.image_path.in_(image_paths))
            .order_by(Image.timestamp.asc())
        ).all():
            path_to_gps.setdefault(path, []).append(gps_row)

    seg_locs = [path_to_location[p] for p in image_paths if p in path_to_location]
    location = None
    if seg_locs:
        most_common_id, _ = Counter(str(loc.id) for loc in seg_locs).most_common(1)[0]
        location = next((loc for loc in seg_locs if str(loc.id) == most_common_id), None)

    images = [_orm_to_grid(r) for r in rows]
    gps_raw = [g for p in image_paths for g in path_to_gps.get(p, [])]
    gps_info = [GPSInfo.model_validate(g, from_attributes=True) for g in gps_raw]

    segment = ResultSegment(
        segment_id=None if unsegmented else segment_id,
        images=images,
        location=LocationInfo.model_validate(location, from_attributes=True) if location else None,
        gps=gps_info,
    )

    today = datetime.now().strftime("%Y-%m-%d")
    # GPS lives on the segment; don't repeat the full list at the top level.
    response = jsonable_encoder({"segments": [segment]})
    ttl = _BROWSE_CACHE_TTL_TODAY if date == today else _BROWSE_CACHE_TTL_PAST
    redis_client.set_json_with_ttl(cache_key, response, ttl)
    return response


class DayStop(CamelCaseModel):
    name: str
    latitude: Coordinate
    longitude: Coordinate
    count: int
    stop: bool


@router.get("/day-stops")
def get_day_stops(
    device: str,
    date: str,
    access_level: Annotated[AccessLevel, Depends(auth_dependency)] = AccessLevel.NONE,
    session: Session = Depends(get_session),
):
    _require_any_access(access_level)
    rows = session.execute(
        select(Location.name, Location.address, Location.latitude, Location.longitude, Location.stop, func.count(Image.id))
        .join(Image, Image.location_id == Location.id)
        .where(
            Image.device == device,
            Image.date == date,
            Image.deleted == False,
            Location.latitude.isnot(None),
            Location.longitude.isnot(None),
        )
        .group_by(Location.id)
    ).all()
    stops = []
    for name, address, lat, lon, stop, count in rows:
        display = name if name and name not in ("---", "Unknown Place", "") else (address or "")
        stops.append(DayStop(name=display, latitude=lat, longitude=lon, count=count, stop=bool(stop)))
    return stops


@router.post("/get-images-by-range", response_model=List[LifelogImage])
def get_images_by_range(
    request: RangeRequest,
    device: str,
    access_level: Annotated[AccessLevel, Depends(auth_dependency)] = AccessLevel.NONE,
    session: Session = Depends(get_session),
):
    _require_owner(access_level)

    start_dt = datetime.fromtimestamp(request.start_time / 1000, tz=timezone.utc)
    end_dt = datetime.fromtimestamp(request.end_time / 1000, tz=timezone.utc)

    rows = (
        session.execute(
            select(Image)
            .where(Image.device == device)
            .where(Image.deleted == False)
            .where(Image.timestamp >= start_dt)
            .where(Image.timestamp <= end_dt)
            .order_by(Image.timestamp.desc())
        )
        .scalars()
        .all()
    )

    records = [_orm_to_lifelog(r) for r in rows]
    _mark_images_not_new(session, [r.image_path for r in records], device)
    return records

@router.get("/get-context-images", response_model=List[ResultSegment])
def get_context_images(
    image: str,
    device: str,
    access_level: Annotated[AccessLevel, Depends(auth_dependency)] = AccessLevel.NONE,
    session: Session = Depends(get_session),
):
    _require_owner(access_level)
    image_record = ImageRecord.find_one(
        session, device=device, image_path=image, deleted=False
    )
    if image_record is None:
        raise HTTPException(status_code=404, detail="Image not found.")

    # segment date first because segment_id can be None
    load_all_segments(session, device, image_record.date, skip_annotations=True)

    timestamp = image_record.timestamp
    # get an hour before and after
    start_dt = timestamp - timedelta(minutes=15)
    end_dt = timestamp + timedelta(minutes=15)
    rows = (
        session.execute(
            select(Image)
            .where(Image.device == device)
            .where(Image.deleted == False)
            .where(Image.timestamp >= start_dt)
            .where(Image.timestamp <= end_dt)
            .order_by(Image.timestamp)
        )
        .scalars()
        .all()
    )
    records = [_orm_to_grid(r) for r in rows]  # type: ignore
    group_by_segment: dict[Optional[int], List[GridImage]] = {}
    for r in records:
        if r.segment_id in group_by_segment:
            group_by_segment[r.segment_id].append(r)
        else:
            group_by_segment[r.segment_id] = [r]

    results = []
    for segment_id, images in group_by_segment.items():
        results.append(
            ResultSegment(
                segment_id=segment_id,
                images=images,
            )
        )
    return results

class GPSData(CamelCaseModel):
    latitude: Coordinate
    longitude: Coordinate

class ObjectData(CamelCaseModel):
    label: str
    confidence: float
    bbox: list[float]  # [x_min, y_min, x_max, y_max]

class PersonData(CamelCaseModel):
    label: str
    confidence: float
    bbox: list[float]
    cluster_id: Optional[str] = None
    cluster_name: Optional[str] = None

class LocationData(CamelCaseModel):
    name: Optional[str]
    address: Optional[str]
    country: Optional[str]

class ImageInfoResponse(CamelCaseModel):
    image_path: str
    timestamp: datetime
    timezone: str
    gps: Optional[GPSData]
    objects: List[ObjectData]
    people: List[PersonData]
    location: Optional[LocationData]

@router.get("/get-image")
def get_image(
    device: str,
    filename: str,
    access_level: Annotated[AccessLevel, Depends(auth_dependency)] = AccessLevel.NONE,
    session: Session = Depends(get_session),
):
    _require_any_access(access_level)

    # image = ImageRecord.find_one(session, device=device, image_path=filename)
    image = session.execute(
        select(Image).where(Image.device == device).where(Image.image_path == filename)
    ).scalar_one_or_none()
    if not image:
        raise HTTPException(status_code=404, detail="Image not found.")

    image_path = os.path.join(DIR, device, filename)
    thumbnail_path, thumbnail_exists = get_thumbnail_path(image_path)
    if not thumbnail_exists:
        if not image.proc_yolo:
            logger.info("Scheduling processing for image %s device %s", filename, device)
            process_image(
                session,
                device,
                filename.split("/")[0],
                filename.split("/")[-1],
                "UTC"
            )
        else:
            logger.info("Scheduling anonymisation for image %s device %s", filename, device)
            anonymise_image_task.delay(
                device,
                image.image_path,
                image.thumbnail
            )
        raise HTTPException(status_code=404, detail="Thumbnail not found.")

    # fetch metadata
    stmt = (select(Image)
            .options(
                selectinload(Image.gps),
                selectinload(Image.objects),
                selectinload(Image.people).selectinload(ImagePerson.cluster),
                selectinload(Image.clip_embedding),
                selectinload(Image.location),
                selectinload(Image.annotations),
            )
            .where(Image.image_path == filename)
            .where(Image.device == device)
    )
    image_metadata = session.execute(stmt).scalar_one_or_none()

    return ImageInfoResponse(
        # Relative path; the client loads the full thumbnail webp directly from
        # the thumbnail host (cacheable, binary) instead of an inline base64 blob.
        image_path=filename,
        timestamp=image.timestamp,
        timezone=image_metadata.gps.timezone if image_metadata and image_metadata.gps else "UTC",
        gps=GPSData(
            latitude=image_metadata.gps.latitude,
            longitude=image_metadata.gps.longitude,
        ) if image_metadata and image_metadata.gps else None,
        objects=[
            ObjectData(
                label=obj.label,
                confidence=obj.confidence,
                bbox=obj.rel_bbox
            )
            for obj in image_metadata.objects
        ] if image_metadata and image_metadata.objects else [],
        people=[
            PersonData(
                label=person.cluster.cluster_label if person.cluster else (person.label or 'Unknown'),
                confidence=person.confidence,
                bbox=person.rel_bbox or [],
                cluster_id=str(person.cluster_id) if person.cluster_id else None,
                cluster_name=person.cluster.cluster_label if person.cluster else None,
            )
            for person in image_metadata.people
        ] if image_metadata and image_metadata.people else [],
        location=LocationData(
            name=image_metadata.location.name,
            address=image_metadata.location.address,
            country=image_metadata.location.country,
        ) if image_metadata and image_metadata.location else None,
    )

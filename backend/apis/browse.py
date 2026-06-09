import base64
import io
import logging
import os
from typing import Annotated, Any, List, Literal, Optional
from fastapi import Depends, FastAPI, HTTPException, Query
from sqlalchemy import update
from sqlalchemy.orm import Session, selectinload
from datetime import datetime, timedelta, timezone

from sqlalchemy.sql import func, select

from app_types.general import LifelogImage, ResultSegment
from auth import _require_owner, _require_any_access
from auth.auth_models import auth_dependency
from auth.types import AccessLevel
from constants import DIR
from database import get_session
from database.models import HeartRateData as HeartRateTable, Image, ImagePerson, MagnetometerData as MagnetometerTable, AccelerometerData as AccelerometerTable, GyroscopeData as GyroscopeTable, PPGData as PPGTable, PPIData as PPITable
from database.types import ImageRecord, _orm_to_lifelog
from dependencies import CamelCaseModel
from scripts.segmentation import load_all_segments
from scripts.utils import get_thumbnail_path
from sessions.redis import redis_client
from PIL import Image as PILImage

logger = logging.getLogger(__name__)
app = FastAPI()

_SEG_COMPLETE_TTL = 60  # seconds to cache "all images segmented" per device/date


def _maybe_load_segments(session: Session, device: str, date: str) -> None:
    """
    Call load_all_segments only if the Redis TTL cache says unsegmented images
    may exist for this device/date. Avoids a DB query on every browse request
    when the day is fully segmented.
    """
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

@app.get("/health")
def health_check():
    return {"status": "ok"}

@app.get("/list-biometrics-sensors")
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


@app.get("/logs/{sensor}")
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

@app.get("/get-images-by-hour", response_model=dict)
async def get_images_by_hour(
    device: str,
    date: str = "",
    hour: str = "",
    page: int = 1,
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

    all_hours = list(
        ImageRecord.distinct(session, "hour", date=date, deleted=False, device=device)
    )
    today = datetime.now().strftime("%Y-%m-%d")
    all_hours = sorted([h for h in all_hours if h is not None], reverse=(today == date))

    if not hour:
        if not all_hours:
            logger.info("No hours for date %s device %s", date, device)
            return {"date": date, "hour": None, "images": []}
        hour = all_hours[0]

    results = ImageRecord.find_segments(
        session,
        date=date,
        device=device,
        deleted=False,
        page=0,
        page_size=10_000,
        hour=hour,
        today=today == date,
    )

    segments = results["segments"]
    gps = results["gps"]
    total_pages = results["total_pages"]

    return {
        "date": date,
        "hour": hour,
        "segments": segments,
        "available_hours": all_hours,
        "total_pages": total_pages,
        "gps": gps,
    }


@app.post("/get-images-by-range", response_model=List[LifelogImage])
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

@app.get("/get-context-images", response_model=List[ResultSegment])
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
    records = [_orm_to_lifelog(r) for r in rows]  # type: ignore
    group_by_segment: dict[Optional[int], List[LifelogImage]] = {}
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
    latitude: float
    longitude: float

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

@app.get("/get-image")
def get_image(
    device: str,
    filename: str,
    access_level: Annotated[AccessLevel, Depends(auth_dependency)] = AccessLevel.NONE,
    session: Session = Depends(get_session),
):
    _require_any_access(access_level)

    image = ImageRecord.find_one(session, device=device, image_path=filename)
    if not image:
        raise HTTPException(status_code=404, detail="Image not found.")

    image_path = os.path.join(DIR, device, filename)
    thumbnail_path, thumbnail_exists = get_thumbnail_path(image_path)
    if not thumbnail_exists:
        raise HTTPException(status_code=404, detail="Thumbnail not found.")

    img = PILImage.open(thumbnail_path)
    buf = io.BytesIO()
    img.save(buf, format="JPEG")

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
        image_path=f"data:image/jpeg;base64, {base64.b64encode(buf.getvalue()).decode('utf-8')}",
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
                label=person.cluster.cluster_label if person.cluster else (person.label or 'person'),
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

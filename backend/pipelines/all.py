from datetime import datetime
import os

from app_types import CustomFastAPI, ProcessedInfo
from constants import DIR, SEARCH_MODEL, THUMBNAIL_DIR
from database.types import ImageRecord
from preprocess import blur_image, compress_image, encode_image, get_thumbnail_path, make_video_thumbnail
from scripts.object_detection import extract_object_from_image


def find_segment(device_id: str, timestamp: float) -> int | None:
    # Find the segment ID for the given image path and timestamp
    end = ImageRecord.find(
        filter={
            "timestamp": {"$gte": timestamp},
            "segment_id": {"$exists": True},
            "device": device_id,
        },
        sort=[("timestamp", 1)],
        limit=1,
    )
    end = list(end)
    end = end[0] if end else None
    if not end:
        # This should belong to a new segment
        return None

    start = ImageRecord.find(
        filter={
            "timestamp": {"$lte": timestamp},
            "segment_id": {"$exists": True},
            "device": device_id,
        },
        sort=[("timestamp", -1)],
        limit=1,
    )
    start = list(start)
    start = start[0] if start else None

    if not start:
        # This should never happen, but just in case
        print("Warning: No start segment found for timestamp", timestamp)
        return None

    if start.segment_id == end.segment_id:
        return start.segment_id

    # Reset all the segments that are greater than end.segment_id
    ImageRecord.update_many(
        filter={"segment_id": {"$gt": end.segment_id}, "device": device_id},
        data={"$inc": {"segment_id": 1}},
    )
    return None

def process_image(app: CustomFastAPI, device_id: str, date: str, file_name: str):
    relative_path = f"{date}/{file_name}"
    model = SEARCH_MODEL

    # Check if features already exist
    if relative_path not in app.features[device_id][model].image_paths:
        feature_exists = True
        _, app.features[device_id][model] = encode_image(
            device_id, f"{date}/{file_name}", app.features[device_id][model]
        )

    # Other checks
    thumbnail_exists = False
    record_exists = False

    _, exists = get_thumbnail_path(f"{DIR}/{device_id}/{date}/{file_name}")
    image_record = ImageRecord.find_one(
        filter={"device": device_id, "image_path": relative_path}
    )

    # Perform necessary processing
    if image_record is not None:
        people = image_record.people
    else:
        timestamp = datetime.strptime(file_name.split(".")[0], "%Y%m%d_%H%M%S")
        objects, people = extract_object_from_image(f"{DIR}/{device_id}/{relative_path}")

    if not thumbnail_exists:
        if people:
            blur_image(image_path=f"{DIR}/{device_id}/{relative_path}", boxes=people)
        else:
            compress_image(f"{DIR}/{device_id}/{date}/{file_name}")

    if image_record is None:
        ImageRecord(
            date=date,
            device=device_id,
            image_path=relative_path,
            thumbnail=relative_path.replace(".jpg", ".webp"),
            timestamp=timestamp.timestamp() * 1000,  # Convert to milliseconds
            is_video=False,
            objects=objects,
            people=people,
            processed=ProcessedInfo(yolo=True, encoded=True),
            segment_id=find_segment(device_id, timestamp.timestamp() * 1000),
        ).create()

    return app


def process_video(app: CustomFastAPI, device_id: str, date: str, file_name: str):
    output_path = f"{DIR}/{device_id}/{date}/{file_name}"
    timestamp = datetime.strptime(file_name.split(".")[0], "%Y%m%d_%H%M%S")
    make_video_thumbnail(output_path)
    ImageRecord(
        device=device_id,
        image_path=f"{date}/{file_name}",
        thumbnail=f"{date}/{file_name.split('.')[0]}.webp",
        date=date,
        timestamp=timestamp.timestamp() * 1000,  # Convert to milliseconds
        is_video=True,
    ).create()

    model = SEARCH_MODEL
    _, app.features[device_id][model] = encode_image(
        device_id, f"{date}/{file_name}", app.features[device_id][model]
    )

    return app

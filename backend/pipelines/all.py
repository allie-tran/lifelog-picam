from scripts.object_detection import extract_object_from_image
from database.types import ImageRecord, ProcessedInfo
from datetime import datetime
from preprocess import compress_image, encode_image, make_video_thumbnail
from constants import DIR
from app_types import CustomFastAPI

def find_segment(timestamp: float) -> int | None:
    # Find the segment ID for the given image path and timestamp
    end = ImageRecord.find(
        filter={
            "timestamp": {"$gte": timestamp},
            "segment_id": {"$exists": True},
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
        },
        sort=[("timestamp", -1)],
        limit=1,
    )
    start = list(start)
    start = start[0] if start else []

    if not start:
        # This should never happen, but just in case
        print("Warning: No start segment found for timestamp", timestamp)
        return None


    if start.segment_id == end.segment_id:
        return start.segment_id

    # Reset all the segments that are greater than end.segment_id
    ImageRecord.update_many(
        filter={"segment_id": {"$gt": end.segment_id}},
        data={"$inc": {"segment_id": 1}},
    )
    return None

def process_image(app: CustomFastAPI, date: str, file_name: str):
    if f"{date}/{file_name}" not in app.image_paths:
        _, app.features, app.image_paths = encode_image(
            f"{date}/{file_name}", app.features, app.image_paths
        )

    try:
        compress_image(f"{DIR}/{date}/{file_name}")
    except Exception as e:
        return app

    relative_path = f"{date}/{file_name}"
    timestamp = datetime.strptime(file_name.split(".")[0], "%Y%m%d_%H%M%S")
    objects, people = extract_object_from_image(f"{DIR}/{relative_path}")

    ImageRecord(
        date=date,
        image_path=relative_path,
        thumbnail=relative_path.replace(".jpg", ".webp"),
        timestamp=timestamp.timestamp() * 1000,  # Convert to milliseconds
        is_video=False,
        objects=objects,
        people=people,
        processed=ProcessedInfo(yolo=True, encoded=True),
        segment_id=find_segment(
            timestamp.timestamp() * 1000
        )
    ).create()

    return app

def process_video(app: CustomFastAPI, date: str, file_name: str):
    output_path = f"{DIR}/{date}/{file_name}"
    timestamp = datetime.strptime(file_name.split(".")[0], "%Y%m%d_%H%M%S")
    make_video_thumbnail(output_path)
    ImageRecord(
        image_path=f"{date}/{file_name}",
        thumbnail=f"{date}/{file_name.split('.')[0]}.webp",
        date=date,
        timestamp=timestamp.timestamp() * 1000,  # Convert to milliseconds
        is_video=True,
    ).create()

    if output_path not in app.image_paths:
        _, app.features, app.image_paths = encode_image(
            output_path, app.features, app.image_paths
        )

    return app


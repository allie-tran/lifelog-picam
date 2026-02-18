from datetime import datetime
import os

import zvec
from app_types import CustomFastAPI, ProcessedInfo
from constants import DIR, SEARCH_MODEL
from database.types import ImageRecord
from database.vector_database import insert_embedding
from pipelines.delete import remove_physical_image
from scripts.anonymise import anonymise_image
from scripts.object_detection import extract_object_from_image
from scripts.utils import get_thumbnail_path, make_video_thumbnail
from visual import clip_model


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


def index_to_mongo(device_id: str, relative_path: str):
    date, file_name = relative_path.split("/")
    timestamp = datetime.strptime(file_name, "%Y%m%d_%H%M%S.jpg")
    ImageRecord(
        date=date,
        device=device_id,
        image_path=relative_path,
        thumbnail="",
        timestamp=timestamp.timestamp() * 1000,  # Convert to milliseconds
        is_video=False,
        objects=[],
        people=[],
        processed=ProcessedInfo(yolo=False, encoded=False, sam3=False),
        segment_id=find_segment(device_id, timestamp.timestamp() * 1000),
    ).create()


def yolo_process_image(device_id: str, relative_path: str):
    objects, people = extract_object_from_image(f"{DIR}/{device_id}/{relative_path}")

    ImageRecord.update_one(
        filter={"device": device_id, "image_path": relative_path},
        data={
            "$set": {
                "objects": objects,
                "people": people,
                "processed.yolo": True,
            }
        },
    )


def create_thumbnail(device_id: str, relative_path: str):
    thumbnail_path, thumbnail_exists = get_thumbnail_path(
        f"{DIR}/{device_id}/{relative_path}"
    )
    if not thumbnail_exists:
        anonymise_image(
            f"{DIR}/{device_id}/{relative_path}", thumbnail_path
        )

    ImageRecord.update_one(
        filter={"device": device_id, "image_path": relative_path},
        data={
            "$set": {
                "thumbnail": relative_path.replace(".jpg", ".webp"),
                "processed.sam3": True,
            }
        },
    )


def encode_image(
    device_id: str,
    image_path: str,
    collection: zvec.Collection,
):
    try:
        path = f"{DIR}/{device_id}/{image_path}"
        if image_path.endswith(".mp4") or image_path.endswith(".h264"):
            # use video thumbnail
            new_path = make_video_thumbnail(f"{DIR}/{device_id}/{image_path}")
            if new_path:
                path = new_path

        vector = clip_model.encode_image(path)
        if len(vector.shape) == 0:
            vector = vector.reshape(1, -1)

        insert_embedding(collection, vector.flatten(), image_path)
    except Exception as e:
        print(e)
        print(f"Error encoding image {image_path}")
        if os.path.exists(f"{DIR}/{device_id}/{image_path}"):
            os.remove(f"{DIR}/{device_id}/{image_path}")


def process_image(
    device_id: str,
    date: str,
    file_name: str,
    collection: zvec.Collection,
):
    relative_path = f"{date}/{file_name}"
    try:
        index_to_mongo(device_id, relative_path)
        yolo_process_image(device_id, relative_path)
        create_thumbnail(device_id, relative_path)
        encode_image(device_id, relative_path, collection)
    except FileNotFoundError as e:
        print(
            f"Error processing image {file_name} for device {device_id} on date {date}: {e}"
        )
        remove_physical_image(device_id, relative_path, collection)


def process_video(device_id: str, date: str, file_name: str, collection: zvec.Collection):
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

    encode_image(
        device_id, f"{date}/{file_name}", collection
    )

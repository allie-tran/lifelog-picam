import os
from constants import DIR, THUMBNAIL_DIR
from database.types import ImageRecord
from database.vector_database import delete_embedding
import zvec
from datetime import datetime


def remove_physical_image(device_id: str, image_path: str, collection: zvec.Collection):
    """Full cleanup"""
    # Physical file
    full_path = os.path.join(DIR, device_id, image_path)
    if os.path.exists(full_path):
        os.remove(full_path)

    # MongoDB
    ImageRecord.delete_many({"image_path": image_path, "device": device_id})

    # Thumbnail
    thumbnail_path = os.path.join(
        THUMBNAIL_DIR, device_id, image_path.replace(".jpg", ".webp")
    )
    if os.path.exists(thumbnail_path):
        os.remove(thumbnail_path)

    # ZVec
    delete_embedding(collection, image_path)
    print(f"Deleted {image_path} from physical storage, MongoDB, thumbnail, and ZVec.")


def mark_error(device_id: str, date: str, image_path: str, timestamp: float):
    """
    This function adds a MongoDB placeholder entry just to tell the device to not keep sending the same image over and over again. It doesn't do any cleanup.
    """
    print(
        f"Marking {image_path} for device {device_id} as deleted in MongoDB to prevent reprocessing."
    )
    ImageRecord.update_one(
        filter={"device": device_id, "image_path": image_path},
        data={
            "$set": {
                "device": device_id,
                "image_path": image_path,
                "deleted": True,
                "delete_time": datetime.now().timestamp(),
                "timestamp": timestamp,
                "isVideo": False,
                "thumbnail": "",
                "date": date,
            }
        },
        upsert=True,
    )

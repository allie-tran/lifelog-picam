import os
import numpy as np
from app_types import CustomFastAPI
from constants import DIR, THUMBNAIL_DIR
from database.types import ImageRecord
from database.vector_database import delete_embedding
import zvec

def remove_physical_image(device_id: str, image_path: str, collection: zvec.Collection):
    """Full cleanup"""
    # Physical file
    full_path = os.path.join(DIR, device_id, image_path)
    if os.path.exists(full_path):
        os.remove(full_path)

    # MongoDB
    ImageRecord.delete_many(
        {"image_path": image_path, "device": device_id}
    )

    # Thumbnail
    thumbnail_path = os.path.join(THUMBNAIL_DIR, device_id, image_path.replace(".jpg", ".webp"))
    if os.path.exists(thumbnail_path):
        os.remove(thumbnail_path)

    # ZVec
    delete_embedding(collection, image_path)
    print(f"Deleted {image_path} from physical storage, MongoDB, thumbnail, and ZVec.")

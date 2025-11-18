import os
import numpy as np
from app_types import CustomFastAPI
from constants import DIR
from database.types import ImageRecord

def remove_physical_image(device_id: str, image_path: str):
    print(f"Force deleting image: {image_path}")
    records = ImageRecord.find(
        {"image_path": image_path, "device": device_id}
    )
    for record in records:
        full_path = os.path.join(DIR, device_id, record.image_path)
        if os.path.exists(full_path):
            os.remove(full_path)
        thumbnail = record.thumbnail
        if thumbnail and os.path.exists(thumbnail):
            os.remove(thumbnail)

def remove_from_features(app: CustomFastAPI, device_id: str, image_path: str):
    if image_path in app.image_paths:
        idx = app.image_paths[device_id].index(image_path)
        app.image_paths[device_id].pop(idx)
        app.features[device_id] = np.delete(app.features[device_id], idx, axis=0)
        print(f"Removed {image_path} from features and image paths.")

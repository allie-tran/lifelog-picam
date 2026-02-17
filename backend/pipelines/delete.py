import os
import numpy as np
from app_types import CustomFastAPI
from constants import DIR
from database.types import ImageRecord
from database.vector_database import delete_embedding

def remove_physical_image(device_id: str, image_path: str):
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

    ImageRecord.delete_many(
        {"image_path": image_path, "device": device_id}
    )

def remove_from_features(app: CustomFastAPI, device_id: str, image_path: str):
    delete_embedding(app.features[device_id]["conclip"].collection, image_path)

    # for model in app.models:
    #     if image_path in app.features[device_id][model].image_paths:
    #         idx = app.features[device_id][model].image_paths.index(image_path)
    #         if app.features[device_id][model].image_paths[idx] != image_path:
    #             idx = app.features[device_id][model].image_paths.index(image_path)
    #         app.features[device_id][model].image_paths.pop(idx)
    #         app.features[device_id][model].features = np.delete(
    #             app.features[device_id][model].features,
    #             idx,
    #             axis=0,
    #         )
    #         print(f"Removed {image_path} from features and image paths.")

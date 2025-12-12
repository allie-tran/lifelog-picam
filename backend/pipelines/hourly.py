import os
from datetime import datetime

import numpy as np
from app_types import CustomFastAPI
from constants import DIR, SEARCH_MODEL
from database.types import ImageRecord
from preprocess import get_thumbnail_path, save_features
from scripts.low_texture import get_pocket_indices
from scripts.low_visual_semantic import get_low_visual_density_indices
from scripts.querybank_norm import load_qb_norm_features
from scripts.segmentation import load_all_segments
from sessions.redis import RedisClient
from tqdm.auto import tqdm

from pipelines.all import process_image

redis_client = RedisClient()


def update_app(app: CustomFastAPI, job_id: str | None = None):
    # Process newly saved images
    changed = process_saved_images(job_id, app)

    # Check deleted files
    check_deleted_images(app)

    # Save updated features
    if changed:
        app.features = save_features(app.features)
        app.last_saved = datetime.now()

    # Load query bank normalization features
    app.retrieved_videos, app.normalizing_sum = load_qb_norm_features(app.features)

    # # Get low visual density images
    app.low_visual_indices, app.images_with_low_density = (
        get_low_visual_density_indices(app.features)
    )

    low_pocket_indices, images_with_pocket = get_pocket_indices(app.features)
    for device_id in app.features.keys():
        app.low_visual_indices[device_id] = np.unique(
            np.concatenate(
                [app.low_visual_indices[device_id], low_pocket_indices[device_id]]
            )
        )
        app.low_visual_indices[device_id] = app.low_visual_indices[device_id].astype(
            np.int32
        )

    app.images_with_low_density = app.images_with_low_density.union(images_with_pocket)

    # Segment images excluding deleted and low visual density images
    for device_id in app.features.keys():
        load_all_segments(
            device_id,
            app.features,
            set(
                ImageRecord.find(filter={"deleted": True}, distinct="image_path")
            ).union(app.images_with_low_density),
            job_id=job_id,
        )
    return app

def check_deleted_images(app: CustomFastAPI):
    for device_id in app.features.keys():
        for model in app.models:
            to_remove = set()
            for index, image_path in enumerate(app.features[device_id][model].image_paths):
                if not os.path.exists(os.path.join(DIR, device_id, image_path)):
                    to_remove.add(index)
            app.features[device_id][model].image_paths = [
                path
                for idx, path in enumerate(app.features[device_id][model].image_paths)
                if idx not in to_remove
            ]
            app.features[device_id][model].features = np.delete(
                app.features[device_id][model].features,
                list(to_remove),
                axis=0,
            )
            app.features[device_id][model].image_paths_to_index = {
                image_path: idx
                for idx, image_path in enumerate(app.features[device_id][model].image_paths)
            }

def process_saved_images(job_id: str | None, app: CustomFastAPI):
    changed = False
    job = redis_client.get_json(f"processing_job:{job_id}") if job_id else None
    tracked_files = job.get("all_files", []) if job else []
    tracked_files_set = set(tracked_files)

    to_process = set()
    model = SEARCH_MODEL

    for device in os.listdir(DIR):
        for root, _, files in os.walk(os.path.join(DIR, device)):
            for file in files:
                relative_path = ""
                if file.endswith(".jpg"):
                    relative_path = os.path.relpath(
                        os.path.join(root, file), os.path.join(DIR, device)
                    )
                elif file.lower().endswith((".h264", ".mp4", ".mov", ".avi")):
                    relative_path = os.path.relpath(
                        os.path.join(root, file), os.path.join(DIR, device)
                    )
                else:
                    continue
                if relative_path not in app.features[device][model].image_paths:
                    to_process.add(f"{device}/{relative_path}")
                    continue

                thumbnail_path, thumbnail_exists = get_thumbnail_path(
                    os.path.join(DIR, device, relative_path)
                )
                if not thumbnail_exists:
                    to_process.add(f"{device}/{relative_path}")

    if to_process:
        print(f"Processing {len(to_process)} new images...")
        i = 0
        for relative_path in tqdm(sorted(to_process), desc="Processing images"):
            process_image(app, *relative_path.split("/", 2))
            if job is not None and relative_path in tracked_files_set:
                job["progress"] += 1 / len(tracked_files) * 0.4
                i += 1
                if i % 100 == 0:
                    job["message"] = (
                        f"Processed {i}/{len(tracked_files)} files. Currently processing: {relative_path}"
                    )
                    redis_client.set_json(f"processing_job:{job_id}", job)
            changed = True

    if job is not None:
        job["progress"] = 0.4
        job["message"] = "Finalizing feature update. Moving to segmentation..."
        redis_client.set_json(f"processing_job:{job_id}", job)

    return changed


def activity_recognition(app: CustomFastAPI):
    # Placeholder for future activity recognition implementation
    return app

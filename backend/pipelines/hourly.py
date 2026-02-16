import os
import random
from datetime import datetime

import numpy as np
from app_types import CustomFastAPI, DeviceFeatures
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
    print(f"Starting hourly update at {datetime.now()} with job_id: {job_id}")
    # Check deleted files
    check_deleted_images(app)

    changed = False
    # Process newly saved images
    changed = process_saved_images(job_id, app)

    # Save updated features
    if changed:
        app.features = save_features(app.features)

    # Load query bank normalization features
    app.retrieved_videos, app.normalizing_sum = load_qb_norm_features(app.features)

    ## Get low visual density images
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
    app.last_saved = datetime.now()
    return app


def check_deleted_images(app: CustomFastAPI):
    for device_id in app.features.keys():
        for model in app.models:
            to_remove = set()
            for index, image_path in enumerate(
                app.features[device_id][model].image_paths
            ):
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
                for idx, image_path in enumerate(
                    app.features[device_id][model].image_paths
                )
            }


def process_saved_images(job_id: str | None, app: CustomFastAPI):
    changed = False
    job = redis_client.get_json(f"processing_job:{job_id}") if job_id else None
    tracked_files = job.get("all_files", []) if job else []
    tracked_files_set = set(tracked_files)

    model = SEARCH_MODEL

    for device in os.listdir(DIR):
        all_dates = os.listdir(os.path.join(DIR, device))
        all_dates = [
            date for date in all_dates if os.path.isdir(os.path.join(DIR, device, date))
        ]

        print("Checking device:", device)
        to_process = set()
        all_encoded = set(app.features[device][model].image_paths)
        _collection = ImageRecord._get_collection()
        all_indexed = _collection.aggregate([ { "$match": { "device": device } }, { "$group": { "_id": "$image_path" } } ])
        all_indexed = set(record["_id"] for record in all_indexed)
        # all_indexed = set(ImageRecord.find(filter={"device": device}, distinct="image_path"))
        all_processed = all_indexed

        for date in all_dates:
            for file in os.listdir(os.path.join(DIR, device, date)):
                relative_path = f"{date}/{file}"
                if relative_path not in all_processed:
                    to_process.add(relative_path)
                    continue
                _, thumbnail_exists = get_thumbnail_path(
                    os.path.join(DIR, device, relative_path)
                )
                if not thumbnail_exists:
                    to_process.add(relative_path)

        if to_process:
            if device not in app.features.keys():
                app.features[device] = DeviceFeatures()
            print(f"Processing {len(to_process)} new images...")

            # split it into batches of 1000 and process each batch
            batch_size = 10000

            # randomize the order of to_process to ensure a good mix of images if the processes are parallelized
            to_process = random.sample(list(to_process), len(to_process))

            for i in range(0, len(to_process), batch_size):
                batch = to_process[i : i + batch_size]
                all_records = ImageRecord.find(
                    filter={"device": device, "image_path": {"$in": batch}},
                )
                all_records_dict = {record.image_path: record for record in all_records}

                j = 0
                for relative_path in tqdm(sorted(batch), desc=f"Processing {device}"):
                    app = process_image(
                        app,
                        device,
                        relative_path.split("/")[0],
                        relative_path.split("/")[1],
                        all_records_dict.get(relative_path),
                        to_encode=True,
                    )

                    if job is not None and relative_path in tracked_files_set:
                        job["progress"] += 1 / len(tracked_files) * 0.4
                        j += 1
                        if j % 100 == 0:
                            job["message"] = (
                                f"Processed {i}/{len(tracked_files)} files. Currently processing: {relative_path}"
                            )
                            redis_client.set_json(f"processing_job:{job_id}", job)

                    changed = True
                app.features = save_features(app.features)

    if job is not None:
        job["progress"] = 0.4
        job["message"] = "Finalizing feature update. Moving to segmentation..."
        redis_client.set_json(f"processing_job:{job_id}", job)

    return changed


def activity_recognition(app: CustomFastAPI):
    # Placeholder for future activity recognition implementation
    return app

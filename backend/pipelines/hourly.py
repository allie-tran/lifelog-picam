from datetime import datetime, timedelta

from app_types import CustomFastAPI
from constants import SEARCH_MODEL
from database.types import ImageRecord
from scripts.segmentation import load_all_segments
from scripts.sync import sync_images
from sessions.redis import RedisClient

redis_client = RedisClient()


def update_app(app: CustomFastAPI, job_id: str | None = None):
    print(f"Starting hourly update at {datetime.now()} with job_id: {job_id}")
    # Process newly saved images
    # process_saved_images(job_id, app)
    if app.last_saved < datetime.now() - timedelta(minutes=24 * 60):
        for device in app.features.keys():
            sync_images(device, app.features[device][SEARCH_MODEL].collection)

    # Segment images excluding deleted and low visual density images
    for device_id in app.features.keys():
        # Let's do day-based
        for date in os.listdir(os.path.join(DIR, device_id)):
            load_all_segments(
                device_id,
                app.features,
                set(
                    ImageRecord.find(
                        filter={"deleted": True, "device": device_id, "date": date}
                    ).distinct("image_path")
                ),
                job_id=job_id,
                date=date,
            )
    app.last_saved = datetime.now()
    return app


# def process_saved_images(job_id: str | None, app: CustomFastAPI):
#     changed = False
#     job = redis_client.get_json(f"processing_job:{job_id}") if job_id else None
#     tracked_files = job.get("all_files", []) if job else []
#     tracked_files_set = set(tracked_files)

#     for device in os.listdir(DIR):
#         all_dates = os.listdir(os.path.join(DIR, device))
#         all_dates = [
#             date for date in all_dates if os.path.isdir(os.path.join(DIR, device, date))
#         ]

#         print("Checking device:", device)
#         to_process = set()

#         _collection = ImageRecord._get_collection()
#         all_indexed = _collection.aggregate([ { "$match": { "device": device } }, { "$group": { "_id": "$image_path" } } ])
#         all_indexed = set(record["_id"] for record in all_indexed)

#         all_processed = all_indexed

#         for date in all_dates:
#             for file in os.listdir(os.path.join(DIR, device, date)):
#                 relative_path = f"{date}/{file}"
#                 if relative_path not in all_processed:
#                     to_process.add(relative_path)
#                     continue
#                 _, thumbnail_exists = get_thumbnail_path(
#                     os.path.join(DIR, device, relative_path)
#                 )
#                 if not thumbnail_exists:
#                     to_process.add(relative_path)

#                 if not check_if_exists(
#                     app.features[device][SEARCH_MODEL].collection,
#                     relative_path,
#                 ):
#                     to_process.add(relative_path)

#         if to_process:
#             if device not in app.features.keys():
#                 app.features[device] = DeviceFeatures()
#             print(f"Processing {len(to_process)} new images...")

#             # split it into batches of 1000 and process each batch
#             batch_size = 10000

#             # randomize the order of to_process to ensure a good mix of images if the processes are parallelized
#             to_process = random.sample(list(to_process), len(to_process))

#             for i in range(0, len(to_process), batch_size):
#                 batch = to_process[i : i + batch_size]
#                 all_records = ImageRecord.find(
#                     filter={"device": device, "image_path": {"$in": batch}},
#                 )
#                 all_records_dict = {record.image_path: record for record in all_records}

#                 j = 0
#                 for relative_path in tqdm(sorted(batch), desc=f"Processing {device}"):
#                     app = process_image(
#                         app,
#                         device,
#                         relative_path.split("/")[0],
#                         relative_path.split("/")[1],
#                         all_records_dict.get(relative_path),
#                         to_encode=True,
#                     )

#                     if job is not None and relative_path in tracked_files_set:
#                         job["progress"] += 1 / len(tracked_files) * 0.4
#                         j += 1
#                         if j % 100 == 0:
#                             job["message"] = (
#                                 f"Processed {i}/{len(tracked_files)} files. Currently processing: {relative_path}"
#                             )
#                             redis_client.set_json(f"processing_job:{job_id}", job)

#                     changed = True

#     if job is not None:
#         job["progress"] = 0.4
#         job["message"] = "Finalizing feature update. Moving to segmentation..."
#         redis_client.set_json(f"processing_job:{job_id}", job)

#     return changed

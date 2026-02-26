from datetime import datetime, timedelta

from app_types import CustomFastAPI
from constants import SEARCH_MODEL
from database.types import ImageRecord
from scripts.face_recognition import delete_old_faces
from scripts.segmentation import load_all_segments
from scripts.sync import sync_images
from sessions.redis import RedisClient

redis_client = RedisClient()


def update_app(app: CustomFastAPI, job_id: str | None = None):
    print(f"Starting hourly update at {datetime.now()} with job_id: {job_id}")
    to_sync = True
    if app.last_saved < datetime.now() - timedelta(minutes=24 * 60):
        print("Last saved was more than 24 hours ago, syncing all images...")
        to_sync = True

    if to_sync:
        for device in app.features.keys():
            collection = app.features[device][SEARCH_MODEL].collection
            assert collection is not None, f"ZVec collection for device {device} is not initialized"
            sync_images(device, collection)

    # Segment images excluding deleted and low visual density images
    today = datetime.now().strftime("%Y-%m-%d")
    days = [today, "2025-11-21"]
    for day in days:
        for device_id in app.features.keys():
            load_all_segments(
                device_id,
                day,
                app.features,
                set(
                    ImageRecord.find(
                        filter={"deleted": True, "device": device_id, "date": today},
                        distinct="image_path",
                    )
                ),
                job_id=job_id,
            )


    # delete old faces
    an_hour_ago = datetime.now() - timedelta(hours=1)
    device_id = "allie"
    collection = app.features[device_id]["faces"].collection
    if collection:
        delete_old_faces(collection, an_hour_ago.timestamp() * 1000)

    # for device_id in app.features.keys():
    #     # Let's do day-based
    #     for date in os.listdir(os.path.join(DIR, device_id)):
    #         load_all_segments(
    #             device_id,
    #             date,
    #             app.features,
    #             set(
    #                 ImageRecord.find(
    #                     filter={"deleted": True, "device": device_id, "date": date},
    #                     distinct="image_path",
    #                 )
    #             ),
    #             job_id=job_id,
    #         )
    app.last_saved = datetime.now()
    return app

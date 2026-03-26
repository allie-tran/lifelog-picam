from datetime import datetime, timedelta
import os

from app_types import CustomFastAPI
from constants import DIR
from scripts.face_recognition import delete_old_faces
from scripts.segmentation import load_all_segments
from scripts.sync import sync_images
from sessions.redis import RedisClient


redis_client = RedisClient()


def update_app(session, app: CustomFastAPI, job_id: str | None = None):
    print(f"Starting hourly update at {datetime.now()} with job_id: {job_id}")
    to_sync = True
    if app.last_saved < datetime.now() - timedelta(minutes=24 * 60):
        print("Last saved was more than 24 hours ago, syncing all images...")
        to_sync = True

    if to_sync:
        for device in os.listdir(DIR):
            if device == "allie" or (job_id and job_id.startswith(device)):
                sync_images(session, device)

    # Segment images excluding deleted and low visual density images
    today = datetime.now().strftime("%Y-%m-%d")

    # delete old faces
    an_hour_ago = datetime.now() - timedelta(hours=1)
    device_id = "allie"
    delete_old_faces(session, device_id, an_hour_ago)

    for device in os.listdir(DIR):
        load_all_segments(
            session,
            device_id,
            today,
            job_id=job_id,
        )
    app.last_saved = datetime.now()
    return app

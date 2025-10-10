import os
import time

from fastapi import BackgroundTasks, FastAPI, HTTPException

from settings.types import PiCamControl

control_app = FastAPI()
picam_username = os.getenv("PICAM_USERNAME", "default_user")


def switch_to_image_mode(picam_username: str, delay: int = 5):
    # Background logic to switch camera to image mode after a delay
    time.sleep(delay)
    settings = PiCamControl.find_one({"username": picam_username})
    if settings and settings.capture_mode == "video":
        settings.capture_mode = "photo"
        settings.update({"$set": {"capture_mode": settings.capture_mode}})
        print(f"Switched {picam_username} to photo mode after {delay} seconds.")

def get_mode():
    settings = PiCamControl.find_one({"username": picam_username})
    return settings.capture_mode if settings else "photo"

@control_app.get("/settings")
async def get_settings():
    settings = PiCamControl.find_one({"username": picam_username})
    return (
        settings.model_dump(
            exclude={"_id", "id"},
            by_alias=True,
        )
        if settings
        else None
    )

@control_app.post("/toggle_mode")
async def toggle_mode(mode: str, background_tasks: BackgroundTasks
                      ):
    settings = PiCamControl.find_one({"username": picam_username})
    if settings:
        if mode in ["photo", "video"]:
            settings.capture_mode = mode
        else:
            settings.capture_mode = (
                "video" if settings.capture_mode == "photo" else "photo"
            )
        if settings.capture_mode == "video":
            background_tasks.add_task(switch_to_image_mode, picam_username, 10)
        settings.update({"$set": {"capture_mode": settings.capture_mode}})
        return settings.model_dump(
            exclude={"_id", "id"},
            by_alias=True,
        )
    else:
        raise HTTPException(
            status_code=404, detail="You can only update existing settings."
        )

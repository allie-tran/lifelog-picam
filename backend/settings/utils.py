from settings.types import PiCamControl
from fastapi import HTTPException

def create_device(device: str):
    if PiCamControl.find_one({"username": device}):
        raise HTTPException(status_code=400, detail="Device already exists.")

    PiCamControl.update_one(
        {"username": device},
        {
            "$setOnInsert": PiCamControl(username=device).model_dump(),
        },
        upsert=True,
    )
    return {"message": f"Device {device} created successfully."}

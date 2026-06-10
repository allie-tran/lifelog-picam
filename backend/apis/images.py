import os
import io
from PIL import UnidentifiedImageError
from PIL import Image as PILImage
from fastapi import BackgroundTasks, Body, Depends, FastAPI, HTTPException, UploadFile

from fastapi import Depends
from fastapi.params import Form
from joblib.memory import traceback
from nacl.public import Box, PrivateKey, PublicKey
from pydantic import BaseModel
from sqlalchemy import select, update
from sqlalchemy.orm import Session


from typing import  Annotated, Optional

from auth.devices import verify_device_and_user
from constants import DIR
from database import get_session

from database.types import ImageRecord
from pipelines.all import process_image
from pipelines.delete import mark_error
from scripts.date_utils import parse_date
from database.models import SensorDevice
from datetime import datetime, timedelta, timezone

from scripts.face_recognition import delete_old_faces


class FastAPIWithTime(FastAPI):
    last_update: dict[str, datetime] = {}

class CheckFilesRequest(BaseModel):
    device_id: str
    date: str
    all_files: list[str]

app = FastAPIWithTime()
# ---------------------------------------------------------------------------
# Root
# ---------------------------------------------------------------------------

@app.get("/health")
def health_check():
    return {"status": "ok"}

# ---------------------------------------------------------------------------
# Upload endpoints
# ---------------------------------------------------------------------------
SERVER_SECRET_KEY = os.getenv("SERVER_SECRET_KEY", "")
assert SERVER_SECRET_KEY, "SERVER_SECRET_KEY is not set in environment variables"
server_sk = PrivateKey(bytes.fromhex(SERVER_SECRET_KEY))


def find_public_key(session: Session, device_id: str) -> Optional[str]:
    key = session.execute(
        select(SensorDevice.secret).where(SensorDevice.device_id == device_id, SensorDevice.sensor_type == "camera")
    ).scalar_one_or_none()

    if key: return key
    raise HTTPException(
        status_code=403, detail="Device secret not found"
    )


def decrypt_image(box: Box, file: UploadFile):
    file.file.seek(0)
    file_bytes = file.file.read()
    try:
        decrypted = box.decrypt(file_bytes)
    except Exception as e:
        traceback.print_exc()
        raise HTTPException(status_code=400, detail="Decryption failed.")
    return PILImage.open(io.BytesIO(decrypted))

@app.put("/upload-image")
async def upload_image(
    file: UploadFile,
    device: Annotated[str, Form(...)],
    tz: Annotated[Optional[str], Form(...)],
    rotation: Annotated[Optional[int], Form(...)],
    background_tasks: BackgroundTasks,
    session: Session = Depends(get_session),
):
    user = verify_device_and_user(session, device, "camera")
    username = str(user.device_id)

    session.execute(
        update(SensorDevice)
        .where(SensorDevice.device_id == device, SensorDevice.sensor_type == "camera")
        .values(last_seen=datetime.now(timezone.utc))
    )
    session.commit()

    file_name = file.filename
    if not file_name:
        raise HTTPException(status_code=400, detail="Filename is required.")

    print(f"Received upload for device {username} with filename {file_name}.")
    timestamp = parse_date(file_name.split(".")[0])
    date = timestamp.strftime("%Y-%m-%d")
    folder = f"{DIR}/{username}/{date}"
    os.makedirs(folder, exist_ok=True)

    if not os.path.exists(f"{folder}/{file_name}"):
        try:
            image = PILImage.open(file.file)
        except UnidentifiedImageError:
            try:
                public_key = find_public_key(session, device)
                box = Box(server_sk, PublicKey(bytes.fromhex(str(public_key))))
                image = decrypt_image(box, file)
            except Exception:
                traceback.print_exc()
                mark_error(
                    session,
                    username,
                    date,
                    f"{date}/{file_name}",
                    timestamp.astimezone(timezone.utc),
                )
                raise HTTPException(status_code=400, detail="Invalid image file.")

        if  rotation is not None:
            image = image.rotate(rotation, expand=True)
            exif = image.getexif()
            exif[274] = 1
        else:
            exif = image.getexif()
        image.save(f"{folder}/{file_name}", exif=exif)
        background_tasks.add_task(
            process_image,
            session,
            username,
            date,
            file_name,
            tz or "UTC"
        )
    now = datetime.now()

    last_updated = app.last_update.get(username)
    if last_updated is None or (now - last_updated) > timedelta(minutes=10):
        app.last_update[username] = now
        an_hour_ago = datetime.now() - timedelta(hours=1)
        delete_old_faces(session, username, an_hour_ago)

    return {"status": "success", "timestamp": now.isoformat()}



@app.post("/check-all-images-uploaded")
def check_all_files_exist(
    request: Annotated[CheckFilesRequest, Body(...)],
    session: Session = Depends(get_session),
):
    user = verify_device_and_user(session, request.device_id, "camera")
    device = str(user.device_id)

    all_files = request.all_files
    date = request.date

    all_dates = {date}
    for f in all_files:
        d = f.split("/")[-1].split("_")[0]
        all_dates.add(f"{d[:4]}-{d[4:6]}-{d[6:]}")

    existing_files: set[str] = set()
    deleted_files: set[str] = set()

    for d in all_dates:
        dir_path = f"{DIR}/{device}/{d}"
        if os.path.exists(dir_path):
            existing_files |= set(os.listdir(dir_path))
            deleted_paths = ImageRecord.distinct(
                session, "image_path", date=d, deleted=True, device=device
            )
            deleted_files |= {f.split("/")[-1] for f in deleted_paths}

    missing_files = [
        f for f in all_files if f not in existing_files and f not in deleted_files
    ]
    to_delete = [f for f in all_files if f in deleted_files]
    return (missing_files, to_delete) if missing_files else ([], list(deleted_files))

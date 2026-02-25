import base64
import io
import os
import traceback
from contextlib import asynccontextmanager
from datetime import datetime
from typing import Annotated, List

import uvicorn
from dotenv import load_dotenv
from fastapi import BackgroundTasks, Depends, HTTPException, Request, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.params import Body
from fastapi_limiter import FastAPILimiter
from nacl.public import Box, PrivateKey, PublicKey
from PIL import Image, UnidentifiedImageError
from pydantic import BaseModel
from redis import asyncio as aioredis
from tqdm.auto import tqdm

from app_types import ActionType, CustomFastAPI, CustomTarget, DaySummary, LifelogImage
from auth import auth_app
from auth.auth_models import auth_dependency, get_user
from auth.devices import verify_device_token
from auth.types import AccessLevel, Device, User
from constants import DIR, LOCAL_PORT, SEARCH_MODEL
from database import init_db
from database.types import DaySummaryRecord, ImageRecord
from dependencies import CamelCaseModel
from ingest import app as ingest_app
from pipelines.all import process_video
from pipelines.delete import remove_physical_image
from pipelines.hourly import update_app
from preprocess import get_similar_images, load_features, retrieve_image
from scripts.anonymise import segment_image_with_sam
from scripts.describe_segments import describe_segment
from scripts.face_recognition import add_face_to_whitelist, search_for_faces
from scripts.segmentation import load_all_segments
from scripts.summary import (
    create_day_timeline,
    summarize_day_by_text,
    summarize_lifelog_by_day,
)
from scripts.utils import get_thumbnail_path
from settings import control_app, get_mode
from settings.types import PiCamControl
from settings.utils import create_device


class RangeRequest(CamelCaseModel):
    date: str
    start_time: int
    end_time: int


class CheckFilesRequest(BaseModel):
    date: str
    all_files: list[str]


class DeleteImageRequest(CamelCaseModel):
    image_path: str


class DeleteImagesRequest(CamelCaseModel):
    image_paths: List[str]


load_dotenv()
picam_username = os.getenv("PICAM_USERNAME", "default_user")


@asynccontextmanager
async def lifespan(app: CustomFastAPI):
    print("Starting up server...")
    init_db()
    registered_devices = os.getenv("REGISTERED_DEVICES", "")
    for device in registered_devices.split(","):
        if not PiCamControl.find_one({"username": device}):
            PiCamControl.update_one(
                {"username": picam_username},
                {
                    "$setOnInsert": PiCamControl(username=picam_username).model_dump(),
                },
                upsert=True,
            )
    redis = aioredis.from_url(
        "redis://localhost:6379", encoding="utf8", decode_responses=True
    )
    await FastAPILimiter.init(redis)
    app.features = load_features(app)
    yield
    await FastAPILimiter.close()


app = CustomFastAPI(lifespan=lifespan)
app.mount("/auth", auth_app)
app.mount("/controls", control_app)
app.mount("/ingest", ingest_app)

load_dotenv()

# Allow CORS for all origins
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "https://mysceal.computing.dcu.ie",
        "https://dcu.allietran.com",
        "*",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/")
async def root():
    return {"message": "Hello, World!"}


# =================================================================================== #
# UPLOAD ENDPOINTS
# =================================================================================== #


@app.get("/check-image")
async def check_image(date: str, timestamp: str):
    """Check if an image exists for the given date and timestamp."""
    try:
        dt = datetime.fromtimestamp(
            int(timestamp) / 1000
        )  # Convert milliseconds to seconds
    except ValueError:
        return {"exists": False, "message": "Invalid timestamp format."}

    file_name = f"{dt.strftime('%Y%m%d_%H%M%S')}.jpg"
    file_path = f"{DIR}/{date}/{file_name}"

    if os.path.exists(file_path):
        print(f"Image {file_name} exists for date {date}.")
        return {"exists": True, "message": f"Image {file_name} exists for date {date}."}
    else:
        return {
            "exists": False,
            "message": f"Image {file_name} does not exist for date {date}.",
        }


def get_device_from_headers(request: Request):
    device_token = request.headers.get("X-Device-ID")
    if not device_token:
        raise HTTPException(status_code=400, detail="Missing X-Device-ID header.")

    # check if device is registered
    device = verify_device_token(device_token)["device"]
    device = PiCamControl.find_one({"username": device})
    if not device:
        raise HTTPException(status_code=403, detail="Device not registered.")
    return device.username


SERVER_SECRET_KEY = os.getenv("SERVER_SECRET_KEY", "")
assert SERVER_SECRET_KEY, "SERVER_SECRET_KEY is not set in environment variables"
server_sk = PrivateKey(bytes.fromhex(SERVER_SECRET_KEY))


def decrypt_image(box: Box, file: UploadFile):
    file.file.seek(0)
    file_bytes = file.file.read()
    decrypted = box.decrypt(file_bytes)
    image = Image.open(io.BytesIO(decrypted))
    return image


@app.put("/upload-image")
async def upload_image(
    file: UploadFile,
    background_tasks: BackgroundTasks,
    device: str = Depends(get_device_from_headers),
):
    file_name = file.filename
    if file_name is None:
        raise HTTPException(status_code=400, detail="Filename is required.")
    timestamp = datetime.strptime(file_name.split(".")[0], "%Y%m%d_%H%M%S")

    date = timestamp.strftime("%Y-%m-%d")
    folder = f"{DIR}/{device}/{date}"
    if not os.path.exists(folder):
        os.makedirs(folder)

    if os.path.exists(f"{folder}/{file_name}"):
        print(f"File {file_name} already exists for date {date}.")
    else:
        print(f"Saving file {file_name} for date {date}.")
        try:
            image = Image.open(file.file)
        except UnidentifiedImageError:
            try:
                device_doc = Device.find_one({"device_id": device})
                if not device_doc or not device_doc.public_key:
                    raise HTTPException(
                        status_code=403, detail="Device public key not found."
                    )
                device_public_key_hex = device_doc.public_key
                box = Box(server_sk, PublicKey(bytes.fromhex(device_public_key_hex)))
                image = decrypt_image(box, file)
            except Exception as e:
                traceback.print_exc()
                print(f"Failed to decrypt image. Error: {e}")
                raise HTTPException(status_code=400, detail="Invalid image file.")

        exif = image.getexif()
        # Rotate 90 degrees if needed
        if image.width > image.height:
            image = image.rotate(-90, expand=True)
            # Update EXIF orientation tag
            exif[274] = 1  # Normal orientation

        # Save image with EXIF data
        output_path = f"{folder}/{file_name}"
        image.save(output_path, exif=exif)
        background_tasks.add_task(
            process_image,
            device,
            date,
            file_name,
            app.features[device]["conclip"].collection
        )

    now = datetime.now()
    if (now - app.last_saved).seconds > 60 * 10:  # autosave every 10 minutes
        update_app(app)
        app.last_saved = now
    return get_mode()


@app.put("/upload-video")
async def upload_video(
    file: UploadFile,
    background_tasks: BackgroundTasks,
    device: str = Depends(get_device_from_headers),
):
    file_name = file.filename
    if file_name is None:
        raise HTTPException(status_code=400, detail="Filename is required.")
    timestamp = datetime.strptime(file_name.split(".")[0], "%Y%m%d_%H%M%S")
    date = timestamp.strftime("%Y-%m-%d")

    folder = f"{DIR}/{device}/{date}"
    if not os.path.exists(folder):
        os.makedirs(folder)

    output_path = f"{folder}/{file_name}"
    with open(output_path, "wb") as f:
        f.write(await file.read())

    # convert h264 to mp4 if needed and rotate 90 degrees
    if file_name.lower().endswith(".h264"):
        mp4_path = output_path[:-5] + ".mp4"
        os.system(
            f"ffmpeg -i {output_path} -c copy {mp4_path} -vn -y -metadata:s:v rotate=90"
        )
        os.remove(output_path)
        output_path = mp4_path

    background_tasks.add_task(
        process_video,
        device,
        date,
        file_name,
        app.features[device]["conclip"].collection,
    )
    return {"message": "Video uploaded successfully."}


@app.post("/update-app")
async def update_app_endpoint(
    job_id: str,
    background_tasks: BackgroundTasks,
):
    background_tasks.add_task(update_app, app, job_id=job_id)
    return {"message": "App update scheduled."}


@app.post("/check-all-images-uploaded")
def check_all_files_exist(
    request: CheckFilesRequest = Body(...),  # type: ignore
    device: str = Depends(get_device_from_headers),
):
    print(request.date, len(request.all_files), request.all_files[:5])
    all_files = request.all_files
    all_dates = [f.split("/")[-1].split("_")[0] for f in all_files]
    all_dates = [f"{d[:4]}-{d[4:6]}-{d[6:]}" for d in all_dates]
    all_dates = set(all_dates)

    date = request.date
    all_dates.add(date)
    if not all_dates:
        return {"message": "Date is required."}

    existing_files = set()
    deleted_files = set()
    for d in all_dates:
        dir_path = f"{DIR}/{device}/{d}"
        if os.path.exists(dir_path):
            files = os.listdir(dir_path)
            existing_files = existing_files.union(set(files))
            deleted = ImageRecord.find(
                filter={"date": d, "deleted": True},
                distinct="image_path",
            )
            deleted = [f.split("/")[-1] for f in deleted]
            deleted_files = deleted_files.union(set(deleted))

    missing_files = [
        f for f in all_files if f not in existing_files and f not in deleted_files
    ]
    to_deleted = [f for f in all_files if f in deleted_files]
    if missing_files:
        return missing_files, to_deleted
    else:
        return [], list(deleted_files)


# =================================================================================== #
# RETRIEVAL ENDPOINTS
# =================================================================================== #
@app.get("/get-devices")
def get_devices(user=Depends(get_user)):
    devices = []
    if user.is_admin:
        for device in PiCamControl.find({}, sort=[("username", 1)]):
            devices.append(device.username)
        return devices
    else:
        for device in user.devices:
            devices.append(device.device_id)
        return devices


@app.get("/create-device")
def create_device_endpoints(
    device: str,
    access_level: Annotated[AccessLevel, Depends(auth_dependency)] = AccessLevel.NONE,
):
    if access_level != AccessLevel.ADMIN:
        raise HTTPException(status_code=403, detail="Not authorized to create devices.")

    create_device(device)
    return {"message": f"Device {device} created successfully."}


@app.get("/get-image")
def get_image(
    device: str,
    filename: str,
    access_level: Annotated[AccessLevel, Depends(auth_dependency)] = AccessLevel.NONE,
):
    if access_level == AccessLevel.NONE:
        print("Access level:", access_level)
        raise HTTPException(status_code=403, detail="Not authorized to access images.")

    image = ImageRecord.find_one(filter={"device": device, "image_path": filename})
    if not image:
        raise HTTPException(status_code=404, detail="Image not found.")

    # Read the image file and return as base64
    image_path = os.path.join(DIR, device, filename)
    if not os.path.exists(image_path):
        raise HTTPException(
            status_code=404, detail=f"Image file not found at {image_path}."
        )

    thumbnail_path, thumbnail_exists = get_thumbnail_path(image_path)
    if not thumbnail_exists:
        raise HTTPException(status_code=404, detail="Thumbnail not found.")
    img = Image.open(thumbnail_path)

    # # Censor if needed (for example, blur faces)
    # img = get_blurred_image(image_path, image.people)

    # Return
    buf = io.BytesIO()
    img.save(buf, format="JPEG")
    byte_im = buf.getvalue()

    base64_image = base64.b64encode(byte_im).decode("utf-8")
    return f"data:image/jpeg;base64, {base64_image}"


@app.get("/get-images-by-hour", response_model=dict)
async def get_images_by_hour(
    device: str,
    date: str = "",
    hour: int = 0,
    page: int = 1,
    access_level: Annotated[AccessLevel, Depends(auth_dependency)] = AccessLevel.NONE,
):

    if access_level != AccessLevel.OWNER and access_level != AccessLevel.ADMIN:
        print("Access level:", access_level)
        raise HTTPException(status_code=403, detail="Not authorized to access images.")

    print(f"Fetching images for date: {date} and hour: {hour}")
    if not date:
        date = datetime.now().strftime("%Y-%m-%d")

    dir_path = f"{DIR}/{device}/{date}"
    if not os.path.exists(dir_path):
        return {"message": f"No images found for date {date}"}

    all_hours = ImageRecord.find(
        filter={"date": date, "deleted": False, "device": device},
        sort=[("image_path", -1)],
        distinct="hour",
    )
    all_hours = list(all_hours)

    if not hour:
        # Get the latest hour
        if not all_hours:
            return {"date": date, "hour": hour, "images": []}
        hour = max(all_hours)
        print(f"No hour specified, using latest hour: {hour}")

    # group by segment_id
    # Take maximum 20 segments per page
    group_pipeline = [
        {
            "$match": {
                "date": date,
                "deleted": False,
                "hour": str(hour).zfill(2),
                "device": device,
            }
        },
        {
            "$group": {
                "_id": "$segment_id",
                "images": {"$push": "$$ROOT"},
            }
        },
        # sort segment by id
        {"$sort": {"_id": -1}},
    ]

    segments = ImageRecord.aggregate(group_pipeline)

    # pagination
    segments = list(segments)

    # Put the null segment_id at the start
    null_segment = [s for s in segments if s.id is None]
    non_null_segments = [s for s in segments if s.id is not None]
    segments = null_segment + non_null_segments

    items_per_page = 20
    total_page = (len(segments) + items_per_page - 1) // items_per_page
    start_index = (page - 1) * items_per_page
    end_index = start_index + items_per_page
    segments = segments[start_index:end_index]

    for segment in segments:
        segment.images = sorted(segment.images, key=lambda x: x.timestamp, reverse=True)

    return {
        "date": date,
        "hour": hour,
        "segments": [
            [
                ImageRecord(**image.dict()).model_dump(
                    exclude={"_id", "id"}, by_alias=True
                )
                for image in segment.images
            ]
            for segment in segments
        ],
        "available_hours": sorted(all_hours, reverse=True),
        "total_pages": total_page,
    }


@app.post("/get-images-by-range", response_model=List[LifelogImage])
def get_images_by_range(
    request: RangeRequest,
    device: str,
    access_level: Annotated[AccessLevel, Depends(auth_dependency)] = AccessLevel.NONE,
):
    if access_level != AccessLevel.OWNER and access_level != AccessLevel.ADMIN:
        print("Access level:", access_level)
        raise HTTPException(status_code=403, detail="Not authorized to access images.")

    start_timestamp = request.start_time
    end_timestamp = request.end_time
    images = ImageRecord.find(
        filter={
            "timestamp": {"$gte": start_timestamp, "$lte": end_timestamp},
            "deleted": False,
            "device": device,
        },
        sort=[("timestamp", -1)],
    )
    return [LifelogImage.model_validate(image) for image in images]


@app.get("/get-all-dates")
def get_all_dates(
    device: str,
    access_level: Annotated[AccessLevel, Depends(auth_dependency)] = AccessLevel.NONE,
):
    """Get all dates with images."""
    if access_level == AccessLevel.NONE:
        raise HTTPException(status_code=403, detail="Not authorized to access images.")

    if not os.path.exists(f"{DIR}/{device}"):
        return []

    dates = []
    for entry in os.listdir(f"{DIR}/{device}"):
        if os.path.isdir(os.path.join(DIR, device, entry)):
            # check if empty
            if len(os.listdir(os.path.join(DIR, device, entry))) == 0:
                os.rmdir(os.path.join(DIR, device, entry))
            dates.append(entry)

    return sorted(dates)


@app.get("/search-images")
def search(
    query: str,
    device: str,
    sort_by: str = "relevance",
    access_level: Annotated[AccessLevel, Depends(auth_dependency)] = AccessLevel.NONE,
):
    if access_level != AccessLevel.OWNER and access_level != AccessLevel.ADMIN:
        raise HTTPException(status_code=403, detail="Not authorized to access images.")

    if not query:
        return []

    deleted_set = set(
        ImageRecord.find(
            filter={
                "deleted": True,
                "device": device,
            },
            distinct="image_path",
        )
    )

    results = retrieve_image(
        device,
        query,
        app.features[device][SEARCH_MODEL],
        sort_by,
        deleted_set,
        k=1000,
        retrieved_videos=app.retrieved_videos[device],
        normalizing_sum=app.normalizing_sum[device],
        remove=app.low_visual_indices[device],
    )
    return results


@app.get("/similar-images")
def similar_images(
    image: str,
    device: str,
    access_level: Annotated[AccessLevel, Depends(auth_dependency)] = AccessLevel.NONE,
):
    if access_level != AccessLevel.OWNER and access_level != AccessLevel.ADMIN:
        raise HTTPException(status_code=403, detail="Not authorized to access images.")

    delete_set = set(
        ImageRecord.find(
            filter={"deleted": True, "device": device}, distinct="image_path"
        )
    )

    results = get_similar_images(
        device,
        image,
        app.features[device][SEARCH_MODEL],
        delete_set,
        k=100,
        retrieved_videos=app.retrieved_videos[device],
        normalizing_sum=app.normalizing_sum[device],
        remove=app.low_visual_indices[device],
    )
    return list(results)


@app.post("/similar-images")
def similar_images_by_upload(
    file: UploadFile,
    device: str,
    access_level: Annotated[AccessLevel, Depends(auth_dependency)] = AccessLevel.NONE,
):
    if access_level != AccessLevel.OWNER and access_level != AccessLevel.ADMIN:
        raise HTTPException(status_code=403, detail="Not authorized to access images.")

    delete_set = set(
        ImageRecord.find(
            filter={"deleted": True, "device": device}, distinct="image_path"
        )
    )
    now = datetime.now()
    if (now - app.last_saved).seconds > 300:  # autosave every 5 minutes
        update_app(app)

    # save in temp
    temp_path = f"{DIR}/{device}/temp_{file.filename}"
    with open(temp_path, "wb") as f:
        f.write(file.file.read())
    try:
        results = get_similar_images(
            device,
            temp_path,
            app.features[device][SEARCH_MODEL],
            delete_set,
            k=100,
            retrieved_videos=app.retrieved_videos[device],
            normalizing_sum=app.normalizing_sum[device],
            remove=app.low_visual_indices[device],
        )
    except UnidentifiedImageError:
        raise HTTPException(status_code=400, detail="Invalid image file.")
    finally:
        os.remove(temp_path)
    return list(results)


# =================================================================================== #
# DELETE / RESTORE ENDPOINTS
# =================================================================================== #


@app.delete("/delete-image")
def delete_image(
    request: DeleteImageRequest,
    device: str,
    access_level: Annotated[AccessLevel, Depends(auth_dependency)] = AccessLevel.NONE,
):
    if access_level != AccessLevel.OWNER and access_level != AccessLevel.ADMIN:
        raise HTTPException(status_code=403, detail="Not authorized to delete images.")

    image_path = request.image_path
    if not (image_path.endswith(".jpg") or image_path.endswith(".mp4")):
        if os.path.exists(f"{DIR}/{device}/{image_path}.jpg"):
            original = f"{image_path}.jpg"
        elif os.path.exists(f"{DIR}/{device}/{image_path}.mp4"):
            original = f"{image_path}.mp4"
        else:
            raise HTTPException(status_code=404, detail="Image not found")
    else:
        original = image_path

    print(f"Deleting image: {original}")
    timestamp_now = datetime.now().timestamp() * 1000
    ImageRecord.update_many(
        {"image_path": original, "device": device},
        {"$set": {"deleted": True, "delete_time": timestamp_now}},
    )


@app.delete("/delete-images")
def delete_images(
    request: DeleteImagesRequest,
    device: str,
    access_level: Annotated[AccessLevel, Depends(auth_dependency)] = AccessLevel.NONE,
):
    if access_level != AccessLevel.OWNER and access_level != AccessLevel.ADMIN:
        raise HTTPException(status_code=403, detail="Not authorized to delete images.")

    image_paths = request.image_paths
    for image_path in image_paths:
        if not (image_path.endswith(".jpg") or image_path.endswith(".mp4")):
            if os.path.exists(f"{DIR}/{device}/{image_path}.jpg"):
                original = f"{image_path}.jpg"
            elif os.path.exists(f"{DIR}/{device}/{image_path}.mp4"):
                original = f"{image_path}.mp4"
            else:
                raise HTTPException(status_code=404, detail="Image not found")
        else:
            original = image_path

        print(f"Deleting image: {original}")
        timestamp_now = datetime.now().timestamp() * 1000
        ImageRecord.update_many(
            {"image_path": original, "device": device},
            {"$set": {"deleted": True, "delete_time": timestamp_now}},
        )


@app.get("/get-deleted-images")
def get_deleted_images(
    device: str,
    access_level: Annotated[AccessLevel, Depends(auth_dependency)] = AccessLevel.NONE,
):
    if access_level != AccessLevel.OWNER and access_level != AccessLevel.ADMIN:
        raise HTTPException(
            status_code=403, detail="Not authorized to access deleted images."
        )

    deleted_list = ImageRecord.find(
        filter={"deleted": True, "device": device}, sort=[("image_path", -1)]
    )
    deleted_list = list(deleted_list)
    print(f"Found {len(deleted_list)} deleted images.")

    now = datetime.now().timestamp() * 1000
    threshold = now - 30 * 24 * 60 * 60 * 1000  # 30 days ago

    final_list = []
    for image in deleted_list:
        if os.path.exists(f"{DIR}/{device}/{image.image_path}"):
            final_list.append(image)

        if image.delete_time and image.delete_time < threshold:
            # Delete image permanently
            full_path = os.path.join(DIR, device, image.image_path)
            print(f"Permanently deleting image: {full_path}")
            collection = app.features[device][SEARCH_MODEL].collection
            assert collection is not None, "Collection is not initialized for device"
            remove_physical_image(device, image.image_path, collection)
            continue
    return final_list


@app.post("/restore-image")
def restore_image(
    request: DeleteImageRequest,
    device: str,
    access_level: Annotated[AccessLevel, Depends(auth_dependency)] = AccessLevel.NONE,
):
    if access_level != AccessLevel.OWNER and access_level != AccessLevel.ADMIN:
        raise HTTPException(status_code=403, detail="Not authorized to restore images.")

    image_path = request.image_path
    ImageRecord.update_many(
        {"image_path": image_path, "device": device},
        {"$set": {"deleted": False}},
    )


@app.delete("/force-delete-image")
def force_delete_image(
    request: DeleteImageRequest,
    device: str,
    access_level: Annotated[AccessLevel, Depends(auth_dependency)] = AccessLevel.NONE,
):
    if access_level != AccessLevel.OWNER and access_level != AccessLevel.ADMIN:
        raise HTTPException(status_code=403, detail="Not authorized to delete images.")
    image_path = request.image_path
    collection = app.features[device][SEARCH_MODEL].collection
    assert collection is not None, "Collection is not initialized for device"
    remove_physical_image(device, image_path, collection)


@app.delete("/force-delete-image")
def force_delete_images(
    request: DeleteImagesRequest,
    device: str,
    access_level: Annotated[AccessLevel, Depends(auth_dependency)] = AccessLevel.NONE,
):
    if access_level != AccessLevel.OWNER and access_level != AccessLevel.ADMIN:
        raise HTTPException(status_code=403, detail="Not authorized to delete images.")
    image_paths = request.image_paths
    collection = app.features[device][SEARCH_MODEL].collection
    assert collection is not None, "Collection is not initialized for device"
    for image_path in image_paths:
        remove_physical_image(device, image_path, collection)


def process_segments(date: str, device: str):
    segments = ImageRecord.find(
        filter={
            "date": date,
            "deleted": False,
            "activity": {"$in": ["", "Unclear"]},
            "device": device,
        },
        distinct="segment_id",
    )
    segments = list(segments)
    print(f"Processing {len(segments)} segments for date {date}.")
    all_summaries = ImageRecord.aggregate(
        [
            {
                "$match": {
                    "date": date,
                    "deleted": False,
                    "activity": {"$ne": ""},
                    "device": device,
                }
            },
            {
                "$group": {
                    "_id": "$segment_id",
                    "summary": {"$first": "$activity_description"},
                }
            },
        ]
    )
    all_summaries = list(all_summaries)[-10:]  # last 10 summaries
    all_summaries = [s.summary for s in all_summaries]
    total = len(segments)
    for _, segment_id in tqdm(
        enumerate(segments), total=total, desc="Processing segments"
    ):
        if segment_id is None:
            continue

        new_description = describe_segment(
            device,
            date,
            [
                img.thumbnail
                for img in ImageRecord.find(
                    filter={
                        "segment_id": segment_id,
                        "deleted": False,
                        "device": device,
                    },
                    sort=[("image_path", 1)],
                )
            ],
            segment_id,
        )
        all_summaries.append(new_description)
        all_summaries = all_summaries[-10:]  # keep last 10 summaries

        DaySummaryRecord.update_one(
            {"date": date, "device": device},
            {"$set": {"updated": True}},
            upsert=True,
        )


@app.get("/process-date")
def process_date(
    date: str,
    device: str,
    reset: bool,
    background_tasks: BackgroundTasks,
    access_level: Annotated[AccessLevel, Depends(auth_dependency)] = AccessLevel.NONE,
):
    if access_level == AccessLevel.NONE:
        raise HTTPException(status_code=403, detail="Not authorized to process date.")

    DaySummaryRecord.update_one(
        {"date": date, "device": device},
        {"$set": {"updated": True}},
        upsert=True,
    )

    if reset:
        print(f"Resetting activities for date {date} and device {device}.")
        ImageRecord.update_many(
            {"date": date, "deleted": False, "device": device},
            {
                "$set": {
                    "activity": "",
                    "activity_description": "",
                    "activity_confidence": "",
                    "segment_id": None,
                }
            },
        )

    load_all_segments(
        device,
        date,
        app.features,
        set(ImageRecord.find(filter={"deleted": True}, distinct="image_path")).union(
            app.images_with_low_density
        ),
    )

    # background_tasks.add_task(process_segments, date, device)
    return {"message": f"Processing segments for date {date} in background."}


DEFAULT_TARGETS = [
    CustomTarget(
        "Phone",
        ActionType.BURST,
        "checking or using a phone (e.g., texting, calling, browsing)",
    ),
    CustomTarget(
        "Computer",
        ActionType.BINARY,
        "using a computer (e.g., typing, video calls, browsing)",
    ),
    CustomTarget("Eating", ActionType.PERIOD, "a photo of a meal on a table"),
]


@app.get("/day-summary", response_model=DaySummary)
def get_day_summary(
    date: str,
    device: str,
    user=Depends(get_user),
    access_level: Annotated[AccessLevel, Depends(auth_dependency)] = AccessLevel.NONE,
):
    if access_level == AccessLevel.NONE:
        raise HTTPException(
            status_code=403, detail="Not authorized to access day summary."
        )

    if not date:
        raise HTTPException(status_code=400, detail="Date is required.")

    # Check if there are changes in the segments
    day_summary_record = DaySummaryRecord.find_one({"date": date, "device": device})
    if day_summary_record and not day_summary_record.updated:
        return day_summary_record

    summary = DaySummary(
        device=device, date=date, segments=[], summary_text="", updated=False
    )
    summary.segments = create_day_timeline(app, device, date)
    if not summary.segments:
        raise HTTPException(status_code=404, detail="No segments found for this date.")

    summary = summarize_day_by_text(summary)
    if user.goal_targets:
        my_targets = user.goal_targets
    else:
        my_targets = DEFAULT_TARGETS

    print(
        f"Summarizing day {date} for device {device} with targets: {[(t.name, t.action_type) for t in my_targets]}"
    )
    summary = summarize_lifelog_by_day(
        summary, app.features[device][SEARCH_MODEL], my_targets
    )

    DaySummaryRecord.update_one(
        {"date": date, "device": device},
        {"$set": summary.model_dump(by_alias=True)},
        upsert=True,
    )

    return summary


@app.get("/get-targets")
def get_targets(
    user=Depends(get_user),
    access_level: Annotated[AccessLevel, Depends(auth_dependency)] = AccessLevel.NONE,
):
    if access_level == AccessLevel.NONE:
        raise HTTPException(status_code=403, detail="Not authorized to access targets.")

    if user.goal_targets:
        return user.goal_targets
    else:
        return DEFAULT_TARGETS


@app.post("/update-targets")
def update_targets(
    targets: List[CustomTarget],
    user=Depends(get_user),
    access_level: Annotated[AccessLevel, Depends(auth_dependency)] = AccessLevel.NONE,
):
    if access_level != AccessLevel.OWNER and access_level != AccessLevel.ADMIN:
        raise HTTPException(status_code=403, detail="Not authorized to set targets.")

    if not targets:
        targets = DEFAULT_TARGETS

    user.goal_targets = targets
    User.update_one({"username": user.username}, {"$set": {"goal_targets": targets}})
    return {"message": "Targets updated successfully."}


class ChangeSegmentActivityRequest(CamelCaseModel):
    date: str
    segment_id: int
    new_activity_info: str


@app.post("/change-segment-activity")
async def change_segment_activity(
    request: ChangeSegmentActivityRequest,
    device: str,
    access_level: Annotated[AccessLevel, Depends(auth_dependency)] = AccessLevel.NONE,
):
    """Change the activity of a specific segment."""
    if access_level != AccessLevel.OWNER and access_level != AccessLevel.ADMIN:
        raise HTTPException(
            status_code=403, detail="Not authorized to change activity."
        )

    segment = ImageRecord.find_one(
        {"segment_id": request.segment_id, "device": device, "date": request.date}
    )
    if not segment or segment.segment_id is None:
        raise HTTPException(status_code=404, detail="Segment not found")

    all_summaries = ImageRecord.aggregate(
        [
            {
                "$match": {
                    "date": segment.date,
                    "deleted": False,
                    "activity": {"$ne": ""},
                    "segment_id": {"$lt": request.segment_id},
                    "device": device,
                }
            },
            {
                "$group": {
                    "_id": "$segment_id",
                    "summary": {"$first": "$activity_description"},
                }
            },
        ]
    )
    all_summaries = list(all_summaries)[-10:]  # last 10 summaries
    all_summaries = [s.summary for s in all_summaries]
    new_description = describe_segment(
        device,
        request.date,
        [
            img.thumbnail
            for img in ImageRecord.find(
                filter={
                    "segment_id": segment.segment_id,
                    "date": request.date,
                    "deleted": False,
                    "device": device,
                },
                sort=[("image_path", 1)],
            )
        ],
        segment.segment_id,
        extra_info=[
            f"The previous activity descriptions were: {', '.join(all_summaries)}.",
            f"Here is the provide activity information from the camera viewer: {request.new_activity_info}. Incorporate this into the description.",
        ],
    )
    ImageRecord.update_many(
        {"segment_id": segment.segment_id, "device": device, "date": request.date},
        {
            "$set": {
                "activity": request.new_activity_info,
                "activity_description": new_description,
            }
        },
    )
    DaySummaryRecord.update_one(
        {"date": request.date, "device": device},
        {"$set": {"updated": True}},
        upsert=True,
    )


@app.post("/get-faces", response_model=List[LifelogImage])
def get_faces(
    files: List[UploadFile],
    device: str,
    access_level: Annotated[AccessLevel, Depends(auth_dependency)] = AccessLevel.NONE,
):
    if access_level == AccessLevel.NONE:
        raise HTTPException(status_code=403, detail="Not authorized to access faces.")

    collection = app.features[device]["faces"].collection
    assert collection is not None, "Face collection is not initialized for device"

    images = search_for_faces(collection, files)
    print(f"Found {len(images)} similar faces for the uploaded image.")
    image_docs = ImageRecord.find(
        filter={"device": device, "image_path": {"$in": images}, "deleted": False},
        sort=[("timestamp", -1)],
    )
    return [LifelogImage.model_validate(image) for image in image_docs]


@app.put("/add-to-whitelist")
def add_to_whitelist(
    files: List[UploadFile],
    device: str,
    name: str,
    access_level: Annotated[AccessLevel, Depends(auth_dependency)] = AccessLevel.NONE,
):
    if access_level != AccessLevel.OWNER and access_level != AccessLevel.ADMIN:
        raise HTTPException(
            status_code=403, detail="Not authorized to modify whitelist."
        )
    add_face_to_whitelist(device, name, files)


class WhitelistEntry(BaseModel):
    name: str
    images: List[str]  # base64 encoded images


@app.get("/get-whitelist", response_model=List[WhitelistEntry])
def get_whitelist(
    device: str,
    access_level: Annotated[AccessLevel, Depends(auth_dependency)] = AccessLevel.NONE,
):
    if access_level != AccessLevel.OWNER and access_level != AccessLevel.ADMIN:
        raise HTTPException(
            status_code=403, detail="Not authorized to access whitelist."
        )
    collection = app.features[device]["faces"].collection
    assert collection is not None, "Face collection is not initialized for device"
    device_obj = Device.find_one({"device_id": device})
    assert device_obj is not None, "Device not found in database"
    whitelist = device_obj.whitelist
    results = []
    for entry in whitelist:
        based64_images = entry.cropped[:2]
        results.append(
            {
                "name": entry.name,
                "images": [f"data:image/jpeg;base64, {img}" for img in based64_images],
            }
        )
    return results


@app.delete("/remove-from-whitelist")
def remove_from_whitelist(
    device: str,
    name: str,
    access_level: Annotated[AccessLevel, Depends(auth_dependency)] = AccessLevel.NONE,
):
    if access_level != AccessLevel.OWNER and access_level != AccessLevel.ADMIN:
        raise HTTPException(
            status_code=403, detail="Not authorized to modify whitelist."
        )
    device_obj = Device.find_one({"device_id": device})
    assert device_obj is not None, "Device not found in database"
    whitelist = device_obj.whitelist
    new_whitelist = [entry for entry in whitelist if entry.name != name]
    Device.update_one(
        {"device_id": device},
        {"$set": {"whitelist": [entry.model_dump() for entry in new_whitelist]}},
    )
    return {"message": f"Removed {name} from whitelist."}


@app.post("/segment-image")
def segment_image(
    file: UploadFile,
):
    visualised_base64 = segment_image_with_sam(Image.open(file.file), [])
    return f"data:image/jpeg;base64, {visualised_base64}"

if __name__ == "__main__":
    uvicorn.run(
        "main:app",
        host="0.0.0.0",
        port=LOCAL_PORT,
        reload=True,
        # workers=2,
        reload_excludes=["./files/QB_norm/*" "./files/**/*"],
    )

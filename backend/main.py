import base64
import os
from contextlib import asynccontextmanager
from datetime import datetime
from typing import Annotated
from tqdm.auto import tqdm

import numpy as np
import redis
from dotenv import load_dotenv
from fastapi import FastAPI, Form, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi_limiter import FastAPILimiter
from PIL import Image, UnidentifiedImageError
from pydantic import BaseModel

from app_types import Array2D
from auth import auth_app
from scripts.segmentation import segment_images
from constants import DIR
from preprocess import (
    compress_image,
    encode_image,
    load_features,
    make_video_thumbnail,
    retrieve_image,
    save_features,
)
from database import init_db
from settings import control_app, get_mode
from settings.types import PiCamControl
from dotenv import load_dotenv

load_dotenv()

class CustomFastAPI(FastAPI):
    features: Array2D[np.float32]
    image_paths: list[str]
    deleted_images: set[str] = set()


picam_username = os.getenv("PICAM_USERNAME", "default_user")
@asynccontextmanager
async def lifespan(app: CustomFastAPI):
    print("Starting up server...")
    init_db()
    if not PiCamControl.find_one({"username": picam_username}):
        PiCamControl.update_one(
            {"username": picam_username},
            {
                "$setOnInsert": PiCamControl(username=picam_username).model_dump(),
            },
            upsert=True,
        )
    redis_connection = redis.from_url("redis://localhost:6379", encoding="utf8")
    await FastAPILimiter.init(redis_connection)
    app.deleted_images = set()
    if os.path.exists("deleted_images.txt"):
        with open("deleted_images.txt", "r") as f:
            app.deleted_images = set(line.strip() for line in f.readlines())
    app.features, app.image_paths = load_features()

    i = 0
    # Create features from DIR first
    to_process = set()
    for root, dirs, files in os.walk(DIR):
        for file in files:
            if file.endswith(".jpg"):
                relative_path = os.path.relpath(os.path.join(root, file), DIR)
                compress_image(os.path.join(root, file))
                if relative_path not in app.image_paths:
                    to_process.add(relative_path)

    if to_process:
        print(f"Processing {len(to_process)} new images...")
        for relative_path in tqdm(sorted(to_process)):
            _, app.features, app.image_paths = encode_image(
                relative_path, app.features, app.image_paths
            )
            i += 1
            assert len(app.features) == len(
                app.image_paths
            ), f"{len(app.features)} != {len(app.image_paths)}"
                    # if i > 100:
                    #     break
    yield
    await FastAPILimiter.close()
    save_features(app.features, app.image_paths)

app = CustomFastAPI(lifespan=lifespan)
app.mount("/auth", auth_app)
app.mount("/controls", control_app)

DIM = 1152
app.features, app.image_paths = np.empty((0, DIM), dtype=np.float32), []
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


@app.get("/save-features")
async def save_features_endpoint():
    save_features(app.features, app.image_paths)
    return {"message": "Features saved successfully."}


@app.get("/check-image-uploaded")
async def check_image_uploaded(timestamp: int):
    try:
        dt = datetime.fromtimestamp(
            int(timestamp) / 1000
        )  # Convert milliseconds to seconds
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid timestamp format.")

    date = dt.strftime("%Y-%m-%d")
    file_name = f"{dt.strftime('%Y%m%d_%H%M%S')}.jpg"
    file_path = f"{DIR}/{date}/{file_name}"

    if os.path.exists(file_path):
        print(f"Image {file_name} exists for date {date}.")
        return True

    raise HTTPException(status_code=404, detail="Image not found")


@app.put("/upload-image")
async def upload_image(file: UploadFile):
    file_name = file.filename
    timestamp = datetime.strptime(file_name.split(".")[0], "%Y%m%d_%H%M%S")

    date = timestamp.strftime("%Y-%m-%d")
    if not os.path.exists(f"{DIR}/{date}"):
        os.makedirs(f"{DIR}/{date}")

    if os.path.exists(f"{DIR}/{date}/{file_name}"):
        print(f"File {file_name} already exists for date {date}.")
    else:
        print(f"Saving file {file_name} for date {date}.")
        # Rotate 90 degrees if needed
        try:
            image = Image.open(file.file)
        except UnidentifiedImageError:
            raise HTTPException(status_code=400, detail="Invalid image file.")
        exif = image.getexif()
        if image.width > image.height:
            image = image.rotate(-90, expand=True)
            # Update EXIF orientation tag
            exif[274] = 1  # Normal orientation
        # Save image with EXIF data
        output_path = f"{DIR}/{date}/{file_name}"
        image.save(output_path, exif=exif)
        _, app.features, app.image_paths = encode_image(
            f"{date}/{file_name}", app.features, app.image_paths
        )
        compress_image(output_path)
    return get_mode()

@app.put("/upload-video")
async def upload_video(file: UploadFile):
    file_name = file.filename
    if file_name is None:
        raise HTTPException(status_code=400, detail="Filename is required.")
    timestamp = datetime.strptime(file_name.split(".")[0], "%Y%m%d_%H%M%S")
    date = timestamp.strftime("%Y-%m-%d")

    if not os.path.exists(f"{DIR}/{date}"):
        os.makedirs(f"{DIR}/{date}")

    output_path = f"{DIR}/{date}/{file_name}"
    with open(output_path, "wb") as f:
        f.write(await file.read())

    # make a webp thumbnail
    make_video_thumbnail(output_path)
    return {"message": "Video uploaded successfully."}

def to_base64(image_data: bytes) -> str:
    """Convert image data to base64 string."""
    return base64.b64encode(image_data).decode("utf-8")


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


@app.get("/get-images", response_model=dict)
async def get_images(date: str = "", page: int = 1):
    print(f"Fetching images for date: {date}")
    if not date:
        date = datetime.now().strftime("%Y-%m-%d")

    dir_path = f"{DIR}/{date}"
    if not os.path.exists(dir_path):
        return {"message": f"No images found for date {date}"}

    all_files = sorted(os.listdir(dir_path), reverse=True)
    print(app.deleted_images)
    all_files = [
        f
        for f in all_files
        if f.endswith(".jpg") and f"{date}/{f}" not in app.deleted_images
    ]
    print(
        [
            (f, f"{date}/{f}", f"{date}/{f}" in app.deleted_images)
            for f in all_files[:10]
        ]
    )

    # Pagination
    items_per_page = 3 * 10
    start_index = (page - 1) * items_per_page
    end_index = start_index + items_per_page
    all_files = all_files[start_index:end_index]

    images = []
    for file_name in all_files:
        timestamp = datetime.strptime(
            file_name.split(".")[0], "%Y%m%d_%H%M%S"
        ).timestamp()
        images.append(
            {
                "image_path": f"{date}/{file_name.split('.')[0]}",
                "timestamp": timestamp * 1000,  # Convert to milliseconds
            }
        )

    return {
        "date": date,
        "images": images,
        "total_pages": (len(os.listdir(dir_path)) + items_per_page - 1)
        // items_per_page,
    }


@app.get("/get-images-by-hour", response_model=dict)
async def get_images_by_hour(date: str = "", hour: int = 0, page: int = 1):
    print(f"Fetching images for date: {date} and hour: {hour}")
    if not date:
        date = datetime.now().strftime("%Y-%m-%d")


    dir_path = f"{DIR}/{date}"
    if not os.path.exists(dir_path):
        return {"message": f"No images found for date {date}"}

    all_files = sorted(os.listdir(dir_path), reverse=True)
    all_files = [
        f
        for f in all_files
        if (f.endswith(".jpg") or f.endswith(".mp4"))
        and f"{date}/{f}" not in app.deleted_images
    ]
    all_hours = set(int(f[9:11]) for f in all_files)
    if not hour:
        # Get the latest hour
        if not all_files:
            return {"date": date, "hour": hour, "images": []}

        hour = max(all_hours)
        print(f"No hour specified, using latest hour: {hour}")

    # Pagination
    items_per_page = 3 * 10
    start_index = (page - 1) * items_per_page
    end_index = start_index + items_per_page

    all_files = [
        f for f in all_files if int(f[9:11]) == hour
    ]
    total_page = (len(all_files) + items_per_page - 1) // items_per_page
    all_files = all_files[start_index:end_index]

    # Get the features and image paths for the filtered files
    indices = [
        app.image_paths.index(f"{date}/{f}")
        for f in all_files
        if f"{date}/{f}" in app.image_paths
    ]
    features = app.features[indices]
    image_paths = [app.image_paths[i] for i in indices]

    segments = segment_images(features, image_paths, app.deleted_images)
    all_images = []
    flat_images = []

    for segment in segments:
        images = []
        for image_path in segment:
            timestamp = datetime.strptime(
                image_path.split("/")[-1].split(".")[0], "%Y%m%d_%H%M%S"
            ).timestamp()
            images.append(
                {
                    "image_path": image_path.split(".")[0],
                    "is_video": image_path.lower().endswith(('.h264', '.mp4', '.mov', '.avi')),
                    "timestamp": timestamp * 1000,  # Convert to milliseconds
                }
            )
        all_images.append(images)
        flat_images.extend(images)

    return {
        "date": date,
        "hour": hour,
        "images": flat_images,
        "segments": all_images,
        "available_hours": sorted(all_hours, reverse=True),
        "total_pages": total_page,
    }

@app.get("/get-all-dates")
def get_all_dates():
    """Get all dates with images."""
    if not os.path.exists(DIR):
        return []

    dates = []
    for entry in os.listdir(DIR):
        if os.path.isdir(os.path.join(DIR, entry)):
            dates.append(entry)

    return sorted(dates)


@app.get("/search-images")
def search(query: str):
    print(len(app.image_paths), "images in the database.")
    print(len(app.features), "features in the database.")
    results = retrieve_image(
        query, app.features, app.image_paths, app.deleted_images, k=20
    )
    return results


@app.get("/login")
def login(password: str):
    if password in os.getenv("ADMIN_PASSWORD", "").split(","):
        save_features(
            app.features, app.image_paths
        )  # TODO!: find a better way to autosave
        return {"success": True}
    else:
        raise HTTPException(status_code=401, detail="Invalid credentials")


class CheckFilesRequest(BaseModel):
    date: str
    all_files: list[str]


@app.post("/check-all-images-uploaded")
def check_all_files_exist(request: CheckFilesRequest):
    print(request.date, len(request.all_files), request.all_files[:5])
    date = request.date
    all_files = request.all_files
    print(f"Checking files for date: {date}")
    if not date:
        return {"message": "Date is required."}

    dir_path = f"{DIR}/{date}"
    if not os.path.exists(dir_path):
        return {"message": f"No images found for date {date}"}

    existing_files = set(os.listdir(dir_path))
    missing_files = [f for f in all_files if f not in existing_files]

    if missing_files:
        return missing_files
    else:
        return []


class DeleteImageRequest(BaseModel):
    image_path: str


@app.delete("/delete-image")
def delete_image(request: DeleteImageRequest):
    image_path = request.image_path
    image_path = f"{image_path}.jpg" if not image_path.endswith(".jpg") else image_path
    print(f"Deleting image: {image_path}")
    if image_path not in app.deleted_images:
        app.deleted_images.add(image_path)
        with open("deleted_images.txt", "a") as f:
            f.write(f"{image_path}\n")


@app.get("/get-deleted-images")
def get_deleted_images():
    deleted_list = list(app.deleted_images)
    deleted_list = sorted(deleted_list, reverse=True)
    print(f"Found {len(deleted_list)} deleted images.")
    timestamps = []
    now = datetime.now().timestamp() * 1000
    threshold = now - 30 * 24 * 60 * 60 * 1000  # 30 days ago

    for image_path in deleted_list:
        timestamp = datetime.strptime(
            image_path.split("/")[-1], "%Y%m%d_%H%M%S.jpg"
        ).timestamp()

        if timestamp * 1000 < threshold:
            # Delete image permanently
            full_path = os.path.join(DIR, image_path)
            if os.path.exists(full_path):
                print("Deleting permanently:", full_path, timestamp * 1000, "<", threshold)
                os.remove(full_path)
            app.deleted_images.remove(image_path)
            continue

        timestamps.append(timestamp * 1000)

    # Update the deleted_images.txt file
    with open("deleted_images.txt", "w") as f:
        for img in app.deleted_images:
            f.write(f"{img}\n")

    return [
        {"image_path": img.split(".")[0], "timestamp": ts}
        for img, ts in zip(deleted_list, timestamps)
    ]


@app.post("/restore-image")
def restore_image(request: DeleteImageRequest):
    image_path = request.image_path
    image_path = f"{image_path}.jpg" if not image_path.endswith(".jpg") else image_path
    if image_path in app.deleted_images:
        app.deleted_images.remove(image_path)
        with open("deleted_images.txt", "w") as f:
            for img in app.deleted_images:
                f.write(f"{img}\n")
    else:
        raise HTTPException(status_code=404, detail="Image not found in deleted list")

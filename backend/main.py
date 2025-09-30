import base64
import os
from datetime import datetime
from typing import Annotated
from pydantic import BaseModel

import numpy as np
from dotenv import load_dotenv
from fastapi import FastAPI, Form, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from PIL import Image, UnidentifiedImageError

from app_types import Array2D
from constants import DIR
from preprocess import (
    compress_image,
    encode_image,
    load_features,
    retrieve_image,
    save_features,
)


class CustomFastAPI(FastAPI):
    features: Array2D[np.float32]
    image_paths: list[str]


app = CustomFastAPI()

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


@app.on_event("startup")
async def startup_event():
    print("Starting up server...")
    app.features, app.image_paths = load_features()

    i = 0
    # Create features from DIR first
    for root, dirs, files in os.walk(DIR):
        for file in files:
            if file.endswith(".jpg"):
                relative_path = os.path.relpath(os.path.join(root, file), DIR)
                compress_image(os.path.join(root, file))
                if relative_path not in app.image_paths:
                    print(f"Processing {relative_path}")
                    _, app.features, app.image_paths = encode_image(
                        relative_path, app.features, app.image_paths
                    )
                    i += 1
                    assert len(app.features) == len(
                        app.image_paths
                    ), f"{len(app.features)} != {len(app.image_paths)}"
            # if i > 100:
            #     break


@app.on_event("shutdown")
async def shutdown_event():
    print("Shutting down server...")
    save_features(app.features, app.image_paths)


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
async def upload_image(file: UploadFile, timestamp: Annotated[str, Form()] = ""):
    if timestamp:
        now = datetime.fromtimestamp(
            int(timestamp) / 1000
        )  # Convert milliseconds to seconds
    else:
        print("No timestamp provided, using current time.")
        now = datetime.now()

    date = now.strftime("%Y-%m-%d")
    if not os.path.exists(f"{DIR}/{date}"):
        os.makedirs(f"{DIR}/{date}")

    file_name = f"{now.strftime('%Y%m%d_%H%M%S')}.jpg"
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
    print(all_files[:10])

    # Pagination
    items_per_page = 3 * 10
    start_index = (page - 1) * items_per_page
    end_index = start_index + items_per_page
    all_files = all_files[start_index:end_index]
    print(all_files)

    images = []
    for file_name in all_files:
        if file_name.endswith(".jpg"):
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
    results = retrieve_image(query, app.features, app.image_paths)
    return results


@app.get("/login")
def login(password: str):
    if password in os.getenv("ADMIN_PASSWORD", "").split(","):
        return {"success": True}
    else:
        raise HTTPException(status_code=401, detail="Invalid credentials")

class CheckFilesRequest(BaseModel):
    date: str
    all_files: list[str]

@app.post("/check-all-images-uploaded")
def check_all_files_exist(request: CheckFilesRequest):
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

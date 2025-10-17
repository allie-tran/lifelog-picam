import base64
import os
from contextlib import asynccontextmanager
from datetime import datetime

import numpy as np
import redis
from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi_limiter import FastAPILimiter
from PIL import Image, UnidentifiedImageError
from pydantic import BaseModel
from tqdm.auto import tqdm

from app_types import Array2D
from auth import auth_app
from constants import DIR
from database import init_db
from database.types import ImageRecord
from dependencies import CamelCaseModel
from preprocess import (compress_image, encode_image, get_similar_images,
                        load_features, make_video_thumbnail, retrieve_image,
                        save_features)
from scripts.low_texture import get_pocket_indices
from scripts.low_visual_semantic import get_low_visual_density_indices
from scripts.querybank_norm import load_qb_norm_features
from scripts.segmentation import load_all_segments, segment_images
from settings import control_app, get_mode
from settings.types import PiCamControl

load_dotenv()


class CustomFastAPI(FastAPI):
    features: Array2D[np.float32]
    image_paths: list[str]

    retrieved_videos: np.ndarray  # Indices of retrieved videos for QB norm
    normalizing_sum: np.ndarray  # Normalizing sum for QB norm
    low_visual_indices: np.ndarray  # Indices of low visual density images
    images_with_low_density: set[str] = set()

    segments: list[list[str]] = []
    image_to_segment: dict[str, int] = {}

    last_saved: datetime = datetime.now()


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
    app.features, app.image_paths = load_features()

    to_process = set()
    for root, _, files in os.walk(DIR):
        for file in files:
            relative_path = ""
            if file.endswith(".jpg"):
                relative_path = os.path.relpath(os.path.join(root, file), DIR)
                compress_image(os.path.join(root, file))
                if relative_path not in app.image_paths:
                    to_process.add(relative_path)
            elif file.lower().endswith((".h264", ".mp4", ".mov", ".avi")):
                relative_path = os.path.relpath(os.path.join(root, file), DIR)
                make_video_thumbnail(os.path.join(root, file))
                if relative_path not in app.image_paths:
                    print(relative_path, "is a video, adding to process list.")
                    to_process.add(relative_path)
            else:
                continue
            # ImageRecord(
            #     image_path=relative_path,
            #     thumbnail=relative_path.replace(".jpg", ".webp").replace(".mp4", ".webp").replace(".h264", ".webp"),
            #     date=relative_path.split("/")[0],
            #     timestamp=datetime.strptime(file.split(".")[0], "%Y%m%d_%H%M%S").timestamp() * 1000,  # Convert to milliseconds
            #     is_video=file.lower().endswith((".h264", ".mp4", ".mov", ".avi"))
            # ).create()

    # Create features from DIR first
    i = 0
    if to_process:
        print(f"Processing {len(to_process)} new images...")
        for relative_path in tqdm(sorted(to_process)):
            _, app.features, app.image_paths = encode_image(
                relative_path, app.features, app.image_paths
            )
            i += 1
            assert (
                relative_path in app.image_paths
            ), f"{relative_path} not in image_paths: {app.image_paths[-1]}"
            assert len(app.features) == len(
                app.image_paths
            ), f"{len(app.features)} != {len(app.image_paths)}"
            ImageRecord(
                image_path=relative_path,
                thumbnail=relative_path.replace(".jpg", ".webp").replace(".mp4", ".webp").replace(".h264", ".webp"),
                date=relative_path.split("/")[0],
                timestamp=datetime.strptime(
                    relative_path.split("/")[-1].split(".")[0], "%Y%m%d_%H%M%S"
                ).timestamp() * 1000,  # Convert to milliseconds
                is_video=relative_path.lower().endswith((".h264", ".mp4", ".mov", ".avi"))
            ).create()

        save_features(app.features, app.image_paths)

    app.retrieved_videos, app.normalizing_sum = load_qb_norm_features(app.features)
    app.low_visual_indices, app.images_with_low_density = (
        get_low_visual_density_indices(app.image_paths)
    )
    low_pocket_indices, images_with_pocket = get_pocket_indices(app.image_paths)
    app.low_visual_indices = np.unique(
        np.concatenate([app.low_visual_indices, low_pocket_indices])
    )
    app.images_with_low_density = app.images_with_low_density.union(images_with_pocket)

    app.image_to_segment, app.segments = load_all_segments(
        app.features,
        app.image_paths,
        set(ImageRecord.find(
            filter={"deleted": True},
            distinct="image_path"
        )).union(app.images_with_low_density),
    )

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
    if file_name is None:
        raise HTTPException(status_code=400, detail="Filename is required.")
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
        ImageRecord(
            image_path=f"{date}/{file_name}",
            thumbnail=f"{date}/{file_name.split('.')[0]}.webp",
            date=date,
            timestamp=timestamp.timestamp() * 1000,  # Convert to milliseconds
            is_video=False,
        ).create()

    now = datetime.now()
    if (now - app.last_saved).seconds > 300:  # autosave every 5 minutes
        save_features(app.features, app.image_paths)
        app.last_saved = now
        deleted_set = set(ImageRecord.find(
            filter={"deleted": True},
            distinct="image_path"
        ))
        app.segments = segment_images(
            app.features,
            app.image_paths,
            deleted_set.union(app.images_with_low_density),
        )
        app.image_to_segment = {
            img: idx for idx, segment in enumerate(app.segments) for img in segment
        }
        app.low_visual_indices, app.images_with_low_density = (
            get_low_visual_density_indices(app.image_paths)
        )
        app.retrieved_videos, app.normalizing_sum = load_qb_norm_features(app.features)
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

    # convert h264 to mp4 if needed and rotate 90 degrees
    if file_name.lower().endswith(".h264"):
        mp4_path = output_path[:-5] + ".mp4"
        os.system(
            f"ffmpeg -i {output_path} -c copy {mp4_path} -vn -y -metadata:s:v rotate=90"
        )
        os.remove(output_path)
        output_path = mp4_path

    make_video_thumbnail(output_path)
    ImageRecord(
        image_path=f"{date}/{file_name}",
        thumbnail=f"{date}/{file_name.split('.')[0]}.webp",
        date=date,
        timestamp=timestamp.timestamp() * 1000,  # Convert to milliseconds
        is_video=True,
    ).create()

    # Add to database as well
    _, app.features, app.image_paths = encode_image(
        output_path, app.features, app.image_paths
    )

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

    all_files = ImageRecord.find(
        filter={"date": date, "deleted": False},
        sort=[("image_path", -1)],
    )
    all_files = [f.image_path.split("/")[-1] for f in all_files]
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
            ImageRecord(
                image_path=f"{date}/{file_name}",
                thumbnail=f"{date}/{file_name.split('.')[0]}.webp",
                date=date,
                timestamp=timestamp * 1000,  # Convert to milliseconds
                is_video=file_name.lower().endswith(
                    (".h264", ".mp4", ".mov", ".avi")
                ),
            )
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

    all_files = ImageRecord.find(
        filter={"date": date, "deleted": False},
        sort=[("image_path", -1)],
    )
    all_files = [f.image_path for f in all_files]
    print(all_files[:10])
    all_hours = set(int(f.split("_")[1][0:2]) for f in all_files)
    if not hour:
        # Get the latest hour
        if not all_files:
            return {"date": date, "hour": hour, "images": []}

        hour = max(all_hours)
        print(f"No hour specified, using latest hour: {hour}")

    # Pagination
    items_per_page = 120
    start_index = (page - 1) * items_per_page
    end_index = start_index + items_per_page

    all_files = [
        f.split("/")[-1]
        for f in all_files
        if f.split("/")[-1].startswith(f"{date.replace('-', '')}_{hour:02d}")
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

    deleted_set = set(ImageRecord.find(
        filter={"deleted": True},
        distinct="image_path"
    ))

    segments = segment_images(features, image_paths, deleted_set.union(app.images_with_low_density))
    all_images = []
    flat_images = []

    for segment in segments:
        images = []
        for image_path in segment:
            timestamp = datetime.strptime(
                image_path.split("/")[-1].split(".")[0], "%Y%m%d_%H%M%S"
            ).timestamp()
            images.append(
                ImageRecord(
                    image_path=image_path,
                    is_video=image_path.lower().endswith(
                        (".h264", ".mp4", ".mov", ".avi")
                    ),
                    date=date,
                    thumbnail=image_path.replace(".jpg", ".webp")
                    .replace(".mp4", ".webp")
                    .replace(".h264", ".webp"),
                    timestamp=timestamp * 1000,  # Convert to milliseconds
                ).model_dump(
                    exclude={"_id", "id"},
                    by_alias=True,
                )
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

    deleted_set = set(ImageRecord.find(
        filter={"deleted": True},
        distinct="image_path"
    ))

    results = retrieve_image(
        query,
        app.features,
        app.image_paths,
        deleted_set,
        k=100,
        retrieved_videos=app.retrieved_videos,
        normalizing_sum=app.normalizing_sum,
        remove=app.low_visual_indices,
    )
    return results


@app.get("/similar-images")
def similar_images(image: str):
    delete_set = set(ImageRecord.find(
        filter={"deleted": True},
        distinct="image_path"
    ))
    results = get_similar_images(
        image,
        app.features,
        app.image_paths,
        delete_set,
        k=100,
        retrieved_videos=app.retrieved_videos,
        normalizing_sum=app.normalizing_sum,
        remove=app.low_visual_indices,
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


class DeleteImageRequest(CamelCaseModel):
    image_path: str


@app.delete("/delete-image")
def delete_image(request: DeleteImageRequest):
    image_path = request.image_path
    if not (image_path.endswith(".jpg") or image_path.endswith(".mp4")):
        if os.path.exists(f"{DIR}/{image_path}.jpg"):
            original = f"{image_path}.jpg"
        elif os.path.exists(f"{DIR}/{image_path}.mp4"):
            original = f"{image_path}.mp4"
        else:
            raise HTTPException(status_code=404, detail="Image not found")
    else:
        original = image_path

    print(f"Deleting image: {original}")
    ImageRecord.update_one(
        {"image_path": original},
        {"$set": {"deleted": True}},
    )


@app.get("/get-deleted-images")
def get_deleted_images():
    deleted_list = ImageRecord.find(
        filter={"deleted": True},
        sort=[("image_path", -1)],
        distinct="image_path"
    )
    deleted_list = list(deleted_list)
    print(f"Found {len(deleted_list)} deleted images.")
    timestamps = []
    now = datetime.now().timestamp() * 1000
    threshold = now - 30 * 24 * 60 * 60 * 1000  # 30 days ago

    for image_path in deleted_list:
        timestamp = datetime.strptime(
            image_path.split("/")[-1].split(".")[0], "%Y%m%d_%H%M%S"
        ).timestamp()

        if timestamp * 1000 < threshold:
            # Delete image permanently
            full_path = os.path.join(DIR, image_path)
            thumbnail = None
            if full_path.endswith(".mp4"):
                thumbnail = make_video_thumbnail(full_path)
            else:
                thumbnail = compress_image(full_path)

            if os.path.exists(full_path):
                print(
                    "Deleting permanently:", full_path, timestamp * 1000, "<", threshold
                )
                os.remove(full_path)
            if thumbnail and os.path.exists(thumbnail):
                os.remove(thumbnail)
            continue

        timestamps.append(timestamp * 1000)

    return [
        ImageRecord(
            image_path=img,
            thumbnail=img.replace(".jpg", ".webp")
            .replace(".mp4", ".webp")
            .replace(".h264", ".webp"),
            date=img.split("/")[0],
            timestamp=ts,
            is_video=img.lower().endswith((".h264", ".mp4", ".mov", ".avi")),
        ).model_dump(exclude={"_id", "id"}, by_alias=True)
        for img, ts in zip(deleted_list, timestamps)
    ]


@app.post("/restore-image")
def restore_image(request: DeleteImageRequest):
    image_path = request.image_path
    ImageRecord.update_one(
        {"image_path": image_path},
        {"$set": {"deleted": False}},
    )

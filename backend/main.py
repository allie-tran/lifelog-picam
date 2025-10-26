import base64
import os
from contextlib import asynccontextmanager
from datetime import datetime, timedelta

import numpy as np
import redis
from dotenv import load_dotenv
from fastapi import BackgroundTasks, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi_limiter import FastAPILimiter
from PIL import Image, UnidentifiedImageError
from pydantic import BaseModel
from tqdm.auto import tqdm

from app_types import CustomFastAPI, DaySummary, SummarySegment
from auth import auth_app
from constants import DIR
from database import init_db
from database.types import DaySummaryRecord, ImageRecord
from dependencies import CamelCaseModel
from pipelines.all import process_image, process_video
from pipelines.hourly import update_app
from preprocess import (
    compress_image,
    get_similar_images,
    load_features,
    make_video_thumbnail,
    retrieve_image,
    save_features,
)
from scripts.describe_segments import describe_segment
from scripts.openai import openai_llm
from settings import control_app, get_mode
from settings.types import PiCamControl

load_dotenv()

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
                # compress_image(os.path.join(root, file))
                if relative_path not in app.image_paths:
                    to_process.add(relative_path)
            elif file.lower().endswith((".h264", ".mp4", ".mov", ".avi")):
                relative_path = os.path.relpath(os.path.join(root, file), DIR)
                # make_video_thumbnail(os.path.join(root, file))
                if relative_path not in app.image_paths:
                    print(relative_path, "is a video, adding to process list.")
                    to_process.add(relative_path)
            else:
                continue
            # timestamp = datetime.strptime(file.split(".")[0], "%Y%m%d_%H%M%S")
            # ImageRecord(
            #     date=relative_path.split("/", 1)[0],
            #     image_path=relative_path,
            #     thumbnail=relative_path.replace(".jpg", ".webp"),
            #     timestamp=timestamp.timestamp() * 1000,  # Convert to milliseconds
            #     is_video=relative_path.lower().endswith(
            #         (".h264", ".mp4", ".mov", ".avi")
            #     ),
            # ).create()

    # Create features from DIR first
    if to_process:
        print(f"Processing {len(to_process)} new images...")
        for relative_path in tqdm(sorted(to_process)):
            process_image(app, *relative_path.split("/", 1))
        app.features, app_image_paths = save_features(app.features, app.image_paths)

    update_app(app)
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
async def upload_image(file: UploadFile, background_tasks: BackgroundTasks):
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
            print("Invalid image file uploaded.")
            # Just save the file without processing
            output_path = f"{DIR}/{date}/{file_name}"
            with open(output_path, "wb") as f:
                f.write(await file.read())
            raise HTTPException(status_code=400, detail="Invalid image file.")

        exif = image.getexif()
        if image.width > image.height:
            image = image.rotate(-90, expand=True)
            # Update EXIF orientation tag
            exif[274] = 1  # Normal orientation
        # Save image with EXIF data
        output_path = f"{DIR}/{date}/{file_name}"
        image.save(output_path, exif=exif)
        background_tasks.add_task(process_image, app, date, file_name)

    now = datetime.now()
    if (now - app.last_saved).seconds > 300:  # autosave every 5 minutes
        background_tasks.add_task(update_app, app)
    return get_mode()


@app.put("/upload-video")
async def upload_video(file: UploadFile, background_tasks: BackgroundTasks):
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

    background_tasks.add_task(process_video, app, date, file_name)
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
                is_video=file_name.lower().endswith((".h264", ".mp4", ".mov", ".avi")),
            )
        )

    return {
        "date": date,
        "images": images,
        "total_pages": (len(os.listdir(dir_path)) + items_per_page - 1),
    }


@app.get("/get-images-by-hour", response_model=dict)
async def get_images_by_hour(date: str = "", hour: int = 0, page: int = 1):
    print(f"Fetching images for date: {date} and hour: {hour}")
    if not date:
        date = datetime.now().strftime("%Y-%m-%d")

    dir_path = f"{DIR}/{date}"
    if not os.path.exists(dir_path):
        return {"message": f"No images found for date {date}"}

    all_hours = ImageRecord.find(
        filter={"date": date, "deleted": False},
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
        {"$match": {"date": date, "deleted": False, "hour": str(hour).zfill(2)}},
        {
            "$group": {
                "_id": "$segment_id",
                "images": {"$push": "$$ROOT"},
            }
        },
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
    start_index = (page - 1) * items_per_page
    end_index = start_index + items_per_page
    segments = segments[start_index:end_index]
    print(f"Found {len(segments)} segments for date {date} and hour {hour}.")

    return {
        "date": date,
        "hour": hour,
        "segments": [
            [
                ImageRecord(**image.dict()).model_dump(
                    exclude={"_id", "id"}, by_alias=True
                )
                for image in segment.images[::-1]
            ]
            for segment in segments
        ],
        "available_hours": sorted(all_hours, reverse=True),
        "total_pages": (len(segments) + items_per_page - 1) // items_per_page,
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

    if not query:
        return []

    deleted_set = set(ImageRecord.find(filter={"deleted": True}, distinct="image_path"))

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
    delete_set = set(ImageRecord.find(filter={"deleted": True}, distinct="image_path"))
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
        dir_path = f"{DIR}/{d}"
        if os.path.exists(dir_path):
            files = os.listdir(dir_path)
            existing_files = existing_files.union(set(files))
            deleted = ImageRecord.find(
                filter={"date": d, "deleted": True},
                distinct="image_path",
            )
            deleted = [f.split("/")[-1] for f in deleted]
            deleted_files = deleted_files.union(set(deleted))

    missing_files = [f for f in all_files if f not in existing_files and f not in deleted_files]
    if missing_files:
        return missing_files, list(deleted_files)
    else:
        return [], list(deleted_files)

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
    ImageRecord.update_many(
        {"image_path": original},
        {"$set": {"deleted": True}},
    )


@app.get("/get-deleted-images")
def get_deleted_images():
    deleted_list = ImageRecord.find(
        filter={"deleted": True}, sort=[("image_path", -1)], distinct="image_path"
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
    ImageRecord.update_many(
        {"image_path": image_path},
        {"$set": {"deleted": False}},
    )


@app.post("/force-delete-image")
def force_delete_image(request: DeleteImageRequest):
    image_path = request.image_path
    print(f"Force deleting image: {image_path}")
    records = ImageRecord.find(
        {"image_path": image_path},
    )
    for record in records:
        full_path = os.path.join(DIR, record.image_path)
        if os.path.exists(full_path):
            os.remove(full_path)
        if thumbnail and os.path.exists(thumbnail):
            os.remove(thumbnail)


def process_segments(date: str):
    segments = ImageRecord.find(
        filter={"date": date, "deleted": False, "activity": ""},
        distinct="segment_id",
    )
    segments = list(segments)
    print(f"Processing {len(segments)} segments for date {date}.")
    for segment_id in tqdm(segments):
        if segment_id is None:
            continue

        describe_segment(
            [
                img.image_path
                for img in ImageRecord.find(
                    filter={"segment_id": segment_id, "deleted": False},
                    sort=[("image_path", 1)],
                )
            ],
            segment_id,
        )

        DaySummaryRecord.update_one(
            {"date": date},
            {"$set": {"updated": True}},
            upsert=True,
        )


@app.get("/process-date")
def process_date(date: str, background_tasks: BackgroundTasks):
    background_tasks.add_task(process_segments, date)
    return {"message": f"Processing segments for date {date} in background."}


@app.get("/day-summary")
def get_day_summary(date: str):

    # summary = []
    # for segment in activities:
    #     segment = segment.dict()
    #     start_time = datetime.fromtimestamp(segment["start_time"] / 1000).strftime(
    #         "%H:%M:%S"
    #     )
    #     end_time = datetime.fromtimestamp(segment["end_time"] / 1000).strftime(
    #         "%H:%M:%S"
    #     )
    #     summary.append(
    #         SummarySegment(
    #             segment_index=segment["_id"],
    #             activity=segment["activity"] or "Unclear",
    #             start_time=start_time,
    #             end_time=end_time,
    #             duration=int((segment["end_time"] - segment["start_time"]) / 1000),
    #         )
    #     )

    # return DaySummary(
    #     date=date,
    #     segments=summary,
    # )

    activities = ImageRecord.aggregate(
        [
            {"$match": {"date": date, "deleted": False, "segment_id": {"$ne": None}}},
            {
                "$group": {
                    "_id": "$segment_id",
                    "activity": {"$first": "$activity"},
                    "start_time": {"$min": "$timestamp"},
                    "end_time": {"$max": "$timestamp"},
                }
            },
            {"$sort": {"start_time": 1}},
        ]
    )

    print("Aggregated activities for day summary.")
    activities = list(activities)

    # Predefine a grid of time slots (e.g., every 30 minutes)
    earliest_hour = 0
    latest_hour = 24
    if activities:
        earliest_hour = datetime.fromtimestamp(activities[0].start_time / 1000).hour
        latest_hour = datetime.fromtimestamp(activities[-1].end_time / 1000).hour + 1

    print("Creating time slots from", earliest_hour, "to", latest_hour)

    time_slots = []
    slot_duration = 15 * 60 * 1000
    for slot_start in range(
        earliest_hour * 60 * 60 * 1000, latest_hour * 60 * 60 * 1000, slot_duration
    ):
        slot_end = slot_start + slot_duration
        time_slots.append((slot_start, slot_end))

    summary = []
    for slot_start, slot_end in time_slots:
        slot_activities = []
        for segment in activities:
            segment = segment.dict()
            if (
                segment["end_time"]
                >= slot_start + datetime.strptime(date, "%Y-%m-%d").timestamp() * 1000
                and segment["start_time"]
                < slot_end + datetime.strptime(date, "%Y-%m-%d").timestamp() * 1000
            ):
                slot_activities.append(segment["activity"] or "Unclear")

        if slot_activities:
            # Choose the most frequent activity in the slot
            activity = max(set(slot_activities), key=slot_activities.count)
        else:
            activity = "No Activity"

        start_time_str = (
            datetime.strptime(date, "%Y-%m-%d") + timedelta(milliseconds=slot_start)
        ).strftime("%H:%M:%S")
        end_time_str = (
            datetime.strptime(date, "%Y-%m-%d") + timedelta(milliseconds=slot_end)
        ).strftime("%H:%M:%S")

        summary.append(
            SummarySegment(
                segment_index=None,
                activity=activity,
                start_time=start_time_str,
                end_time=end_time_str,
                duration=int(slot_duration / 1000),
            )
        )

    updated = True
    day_summary_record = DaySummaryRecord.find_one({"date": date})
    if (
        day_summary_record
        and not day_summary_record.updated
        and day_summary_record.summary_text
    ):
        day_summary = day_summary_record.summary_text
        updated = False
    else:
        try:
            raw_activities = ImageRecord.aggregate(
                [
                    {
                        "$match": {
                            "date": date,
                            "deleted": False,
                            "segment_id": {"$ne": None},
                        }
                    },
                    {
                        "$group": {
                            "_id": "$segment_id",
                            "activity": {"$first": "$activity"},
                            "activity_description": {"$first": "$activity_description"},
                            "start_time": {"$min": "$timestamp"},
                            "end_time": {"$max": "$timestamp"},
                        }
                    },
                    {"$sort": {"start_time": 1}},
                ]
            )

            day_summary = openai_llm.generate_from_text(
                "Create a summary of the activities performed during the day based on the following segments. Make it concise and informative. Such as: you spent the morning working, had lunch at 1 PM, spent the afternoon relaxing, and in the evening you went for a walk.\n"
                "Ignore unclear activities.\n"
                + "\n".join(
                    [
                        f"{seg.start_time} to {seg.end_time}: {seg.activity_description}"
                        for seg in raw_activities
                        if seg.activity != "No Activity"
                    ]
                )
            )
            print("Day Summary LLM Response:")
            print(day_summary)
            day_summary = str(day_summary).strip()
            updated = False

        except Exception as e:
            trace = str(e)
            print("Failed to generate day summary:", trace)
            day_summary = "No summary available."

    summary = DaySummary(
        date=date, segments=summary, summary_text=day_summary, updated=updated
    )
    DaySummaryRecord.update_one(
        {"date": date},
        {"$set": summary.model_dump(by_alias=True)},
        upsert=True,
    )

    return summary

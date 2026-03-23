import base64
import io
import os
import traceback
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from typing import Annotated, List, Optional

import uvicorn
from dotenv import load_dotenv
from fastapi import BackgroundTasks, Depends, HTTPException, Request, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.params import Body
from nacl.public import Box, PrivateKey, PublicKey
from PIL import Image, UnidentifiedImageError
from pydantic import BaseModel
from sqlalchemy import update
from sqlalchemy.orm import Session
from tqdm.auto import tqdm

from app_types import ActionType, CustomFastAPI, CustomTarget, DaySummary, LifelogImage
from auth import auth_app
from auth.auth_models import auth_dependency, get_user
from auth.devices import verify_device_token
from auth.types import AccessLevel, Device, User
from constants import DIR, LOCAL_PORT, SEARCH_MODEL, THUMBNAIL_DIR
from database import init_db, get_session
from database.types import DaySummaryRecord, ImageRecord
from database.models import Image as ImageModel
from dependencies import CamelCaseModel
from tasks import describe_segment_task
from ingest import app as ingest_app
from pipelines.all import process_video, process_image
from pipelines.delete import mark_error, remove_physical_image
from pipelines.hourly import update_app
from preprocess import get_similar_images, load_features, retrieve_image, save_features
from scripts.anonymise import segment_image_with_sam
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


# ---------------------------------------------------------------------------
# Request models
# ---------------------------------------------------------------------------


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


class ChangeSegmentActivityRequest(CamelCaseModel):
    date: str
    segment_id: int
    new_activity_info: str


class WhitelistEntry(BaseModel):
    name: str
    images: List[str]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

load_dotenv()
picam_username = os.getenv("PICAM_USERNAME", "default_user")
SERVER_SECRET_KEY = os.getenv("SERVER_SECRET_KEY", "")
assert SERVER_SECRET_KEY, "SERVER_SECRET_KEY is not set in environment variables"
server_sk = PrivateKey(bytes.fromhex(SERVER_SECRET_KEY))

ITEMS_PER_PAGE = 20

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


def _require_owner_or_admin(access_level: AccessLevel):
    if access_level not in (AccessLevel.OWNER, AccessLevel.ADMIN):
        raise HTTPException(status_code=403, detail="Not authorized.")


def _require_any_access(access_level: AccessLevel):
    if access_level == AccessLevel.NONE:
        raise HTTPException(status_code=403, detail="Not authorized.")


def _require_admin(access_level: AccessLevel):
    if access_level != AccessLevel.ADMIN:
        raise HTTPException(status_code=403, detail="Not authorized.")


def decrypt_image(box: Box, file: UploadFile):
    file.file.seek(0)
    file_bytes = file.file.read()
    decrypted = box.decrypt(file_bytes)
    return Image.open(io.BytesIO(decrypted))


def get_device_from_headers(request: Request):
    device_token = request.headers.get("X-Device-ID")
    if not device_token:
        raise HTTPException(status_code=400, detail="Missing X-Device-ID header.")
    device = verify_device_token(device_token)["device"]
    device = PiCamControl.find_one({"username": device})
    if not device:
        raise HTTPException(status_code=403, detail="Device not registered.")
    return device.username


def _mark_images_not_new(session: Session, image_paths: list[str], device: str):
    if not image_paths:
        return
    session.execute(
        update(ImageModel)
        .where(ImageModel.image_path.in_(image_paths))
        .where(ImageModel.device == device)
        .values(new=False)
    )
    session.flush()


def _bulk_delete(session: Session, image_paths: list[str], device: str):
    now = datetime.now(timezone.utc).timestamp() * 1000
    session.execute(
        update(ImageModel)
        .where(ImageModel.image_path.in_(image_paths))
        .where(ImageModel.device == device)
        .values(deleted=True, delete_time=now)
    )
    session.flush()


def _get_last_n_summaries(
    session: Session,
    date: str,
    device: str,
    n: int = 10,
    segment_id_lt: Optional[int] = None,
) -> list[str]:
    """Get the last n activity descriptions for context, optionally filtered by segment_id."""
    from sqlalchemy import select, desc

    stmt = (
        select(ImageModel.segment_id, ImageModel.activity_description)
        .where(ImageModel.date == date)
        .where(ImageModel.deleted == False)
        .where(ImageModel.activity != "")
        .where(ImageModel.device == device)
        .distinct(ImageModel.segment_id)
        .order_by(desc(ImageModel.segment_id))
        .limit(n)
    )
    if segment_id_lt is not None:
        stmt = stmt.where(ImageModel.segment_id < segment_id_lt)
    rows = session.execute(stmt).fetchall()
    return [row.activity_description for row in reversed(rows)]


# ---------------------------------------------------------------------------
# Lifespan
# ---------------------------------------------------------------------------


@asynccontextmanager
async def lifespan(app: CustomFastAPI):
    print("Starting up server...")
    init_db()
    registered_devices = os.getenv("REGISTERED_DEVICES", "")
    for device in registered_devices.split(","):
        if not PiCamControl.find_one({"username": device}):
            PiCamControl.update_one(
                {"username": picam_username},
                {"$setOnInsert": PiCamControl(username=picam_username).model_dump()},
                upsert=True,
            )
    app.features = load_features(app)
    yield
    save_features(app)


# ---------------------------------------------------------------------------
# App setup
# ---------------------------------------------------------------------------

app = CustomFastAPI(lifespan=lifespan)
app.mount("/auth", auth_app)
app.mount("/controls", control_app)
app.mount("/ingest", ingest_app)

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


# ---------------------------------------------------------------------------
# Root
# ---------------------------------------------------------------------------


@app.get("/")
async def root():
    return {"message": "Hello, World!"}


# ---------------------------------------------------------------------------
# Upload endpoints
# ---------------------------------------------------------------------------


@app.get("/check-image")
async def check_image(date: str, timestamp: str):
    try:
        dt = datetime.fromtimestamp(int(timestamp) / 1000)
    except ValueError:
        return {"exists": False, "message": "Invalid timestamp format."}

    file_name = f"{dt.strftime('%Y%m%d_%H%M%S')}.jpg"
    file_path = f"{DIR}/{date}/{file_name}"
    exists = os.path.exists(file_path)
    return {
        "exists": exists,
        "message": f"Image {file_name} {'exists' if exists else 'does not exist'} for date {date}.",
    }


@app.put("/upload-image")
async def upload_image(
    file: UploadFile,
    background_tasks: BackgroundTasks,
    device: str = Depends(get_device_from_headers),
    session: Session = Depends(get_session),
):
    file_name = file.filename
    if not file_name:
        raise HTTPException(status_code=400, detail="Filename is required.")

    timestamp = datetime.strptime(file_name.split(".")[0], "%Y%m%d_%H%M%S")
    date = timestamp.strftime("%Y-%m-%d")
    folder = f"{DIR}/{device}/{date}"
    os.makedirs(folder, exist_ok=True)

    if not os.path.exists(f"{folder}/{file_name}"):
        try:
            image = Image.open(file.file)
        except UnidentifiedImageError:
            try:
                device_doc = Device.find_one({"device_id": device})
                if not device_doc or not device_doc.public_key:
                    raise HTTPException(
                        status_code=403, detail="Device public key not found."
                    )
                box = Box(server_sk, PublicKey(bytes.fromhex(device_doc.public_key)))
                image = decrypt_image(box, file)
            except Exception as e:
                traceback.print_exc()
                mark_error(
                    device, date, f"{date}/{file_name}", timestamp.timestamp() * 1000
                )
                raise HTTPException(status_code=400, detail="Invalid image file.")

        if image.width > image.height:
            image = image.rotate(-90, expand=True)
            exif = image.getexif()
            exif[274] = 1
        else:
            exif = image.getexif()

        image.save(f"{folder}/{file_name}", exif=exif)

        conclip_collection = app.features[device]["conclip"].collection
        face_collection = app.features[device]["faces"].collection
        assert conclip_collection is not None, "Conclip collection not initialized"
        assert (
            face_collection is not None
        ), f"Face collection not initialized for {device}"

        background_tasks.add_task(
            process_image,
            device,
            date,
            file_name,
            conclip_collection,
            face_collection,
            session,
        )

    now = datetime.now()
    if (now - app.last_saved).seconds > 60 * 10:
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
    if not file_name:
        raise HTTPException(status_code=400, detail="Filename is required.")

    timestamp = datetime.strptime(file_name.split(".")[0], "%Y%m%d_%H%M%S")
    date = timestamp.strftime("%Y-%m-%d")
    folder = f"{DIR}/{device}/{date}"
    os.makedirs(folder, exist_ok=True)

    output_path = f"{folder}/{file_name}"
    with open(output_path, "wb") as f:
        f.write(await file.read())

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
async def update_app_endpoint(job_id: str, background_tasks: BackgroundTasks):
    background_tasks.add_task(update_app, app, job_id=job_id)
    return {"message": "App update scheduled."}


@app.post("/check-all-images-uploaded")
def check_all_files_exist(
    request: CheckFilesRequest = Body(...),
    device: str = Depends(get_device_from_headers),
    session: Session = Depends(get_session),
):
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


# ---------------------------------------------------------------------------
# Retrieval endpoints
# ---------------------------------------------------------------------------


@app.get("/get-devices")
def get_devices(user=Depends(get_user)):
    if user.is_admin:
        return [d.username for d in PiCamControl.find({}, sort=[("username", 1)])]
    return [d.device_id for d in user.devices]


@app.get("/create-device")
def create_device_endpoint(
    device: str,
    access_level: Annotated[AccessLevel, Depends(auth_dependency)] = AccessLevel.NONE,
):
    _require_admin(access_level)
    create_device(device)
    return {"message": f"Device {device} created successfully."}


@app.get("/get-image")
def get_image(
    device: str,
    filename: str,
    access_level: Annotated[AccessLevel, Depends(auth_dependency)] = AccessLevel.NONE,
    session: Session = Depends(get_session),
):
    _require_any_access(access_level)

    image = ImageRecord.find_one(session, device=device, image_path=filename)
    if not image:
        raise HTTPException(status_code=404, detail="Image not found.")

    image_path = os.path.join(DIR, device, filename)
    thumbnail_path, thumbnail_exists = get_thumbnail_path(image_path)
    if not thumbnail_exists:
        raise HTTPException(status_code=404, detail="Thumbnail not found.")

    img = Image.open(thumbnail_path)
    buf = io.BytesIO()
    img.save(buf, format="JPEG")
    return f"data:image/jpeg;base64, {base64.b64encode(buf.getvalue()).decode('utf-8')}"


@app.get("/get-images-by-hour", response_model=dict)
async def get_images_by_hour(
    device: str,
    date: str = "",
    hour: int = 0,
    page: int = 1,
    access_level: Annotated[AccessLevel, Depends(auth_dependency)] = AccessLevel.NONE,
    session: Session = Depends(get_session),
):
    _require_owner_or_admin(access_level)

    if not date:
        date = datetime.now().strftime("%Y-%m-%d")

    dir_path = f"{DIR}/{device}/{date}"
    if not os.path.exists(dir_path):
        return {"message": f"No images found for date {date}"}

    all_hours = sorted(
        ImageRecord.distinct(session, "hour", date=date, deleted=False, device=device),
        reverse=True,
    )

    if not hour:
        if not all_hours:
            print(f"No hours found for date {date} and device {device}.")
            return {"date": date, "hour": None, "images": []}
        print(all_hours)
        hour = all_hours[0]

    all_segments = ImageRecord.find_segments(
        session,
        date=date,
        hour=hour,
        device=device,
        deleted=False,
        page=0,
        page_size=10_000,
    )

    null_segments = [s for s in all_segments if s["segment_id"] is None]
    non_null_segments = sorted(
        [s for s in all_segments if s["segment_id"] is not None],
        key=lambda s: s["segment_id"],
        reverse=True,
    )
    all_segments = null_segments + non_null_segments

    total_pages = max(1, (len(all_segments) + ITEMS_PER_PAGE - 1) // ITEMS_PER_PAGE)
    start = (page - 1) * ITEMS_PER_PAGE
    segments = all_segments[start : start + ITEMS_PER_PAGE]

    for segment in segments:
        segment["images"].sort(key=lambda img: img.timestamp, reverse=True)

    _mark_images_not_new(
        session,
        [img.image_path for s in segments for img in s["images"]],
        device,
    )

    serialized_segments = []
    gps = []
    for segment in segments:
        serialized = [img.model_dump(by_alias=True) for img in segment["images"]]
        serialized_segments.append(serialized)
        gps.extend(img["gps"] for img in serialized if img.get("gps") is not None)

    return {
        "date": date,
        "hour": hour,
        "segments": serialized_segments,
        "available_hours": all_hours,
        "total_pages": total_pages,
        "gps": gps,
    }


@app.post("/get-images-by-range", response_model=List[LifelogImage])
def get_images_by_range(
    request: RangeRequest,
    device: str,
    access_level: Annotated[AccessLevel, Depends(auth_dependency)] = AccessLevel.NONE,
    session: Session = Depends(get_session),
):
    _require_owner_or_admin(access_level)

    from sqlalchemy import select
    from datetime import datetime, timezone

    start_dt = datetime.fromtimestamp(request.start_time / 1000, tz=timezone.utc)
    end_dt = datetime.fromtimestamp(request.end_time / 1000, tz=timezone.utc)

    rows = (
        session.execute(
            select(ImageModel)
            .where(ImageModel.device == device)
            .where(ImageModel.deleted == False)
            .where(ImageModel.timestamp >= start_dt)
            .where(ImageModel.timestamp <= end_dt)
            .order_by(ImageModel.timestamp.desc())
        )
        .scalars()
        .all()
    )

    _mark_images_not_new(session, [r.image_path for r in rows], device)

    from database.types import _orm_to_lifelog

    return [_orm_to_lifelog(r) for r in rows]


@app.get("/get-gps-by-date")
def get_gps_by_date(
    date: str,
    device: str,
    access_level: Annotated[AccessLevel, Depends(auth_dependency)] = AccessLevel.NONE,
    session: Session = Depends(get_session),
):
    _require_owner_or_admin(access_level)

    images = ImageRecord.find(
        session,
        date=date,
        deleted=False,
        device=device,
        sort="timestamp",
        sort_desc=True,
    )
    return [img.gps for img in images if img.gps is not None]


@app.get("/get-all-dates")
def get_all_dates(
    device: str,
    access_level: Annotated[AccessLevel, Depends(auth_dependency)] = AccessLevel.NONE,
):
    _require_any_access(access_level)

    device_dir = f"{DIR}/{device}"
    if not os.path.exists(device_dir):
        return []

    dates = []
    for entry in os.listdir(device_dir):
        full = os.path.join(DIR, device, entry)
        if os.path.isdir(full):
            if not os.listdir(full):
                os.rmdir(full)
            else:
                dates.append(entry)
    return sorted(dates)


@app.get("/search-images")
def search(
    query: str,
    device: str,
    sort_by: str = "relevance",
    access_level: Annotated[AccessLevel, Depends(auth_dependency)] = AccessLevel.NONE,
    session: Session = Depends(get_session),
):
    _require_owner_or_admin(access_level)

    if not query:
        return []

    deleted_set = set(
        ImageRecord.distinct(session, "image_path", deleted=True, device=device)
    )

    return retrieve_image(
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


@app.get("/similar-images")
def similar_images(
    image: str,
    device: str,
    access_level: Annotated[AccessLevel, Depends(auth_dependency)] = AccessLevel.NONE,
    session: Session = Depends(get_session),
):
    _require_owner_or_admin(access_level)

    delete_set = set(
        ImageRecord.distinct(session, "image_path", deleted=True, device=device)
    )

    return list(
        get_similar_images(
            device,
            image,
            app.features[device][SEARCH_MODEL],
            delete_set,
            k=100,
            retrieved_videos=app.retrieved_videos[device],
            normalizing_sum=app.normalizing_sum[device],
            remove=app.low_visual_indices[device],
        )
    )


@app.post("/similar-images")
def similar_images_by_upload(
    file: UploadFile,
    device: str,
    access_level: Annotated[AccessLevel, Depends(auth_dependency)] = AccessLevel.NONE,
    session: Session = Depends(get_session),
):
    _require_owner_or_admin(access_level)

    delete_set = set(
        ImageRecord.distinct(session, "image_path", deleted=True, device=device)
    )
    temp_path = f"{DIR}/{device}/temp_{file.filename}"

    with open(temp_path, "wb") as f:
        f.write(file.file.read())
    try:
        results = list(
            get_similar_images(
                device,
                temp_path,
                app.features[device][SEARCH_MODEL],
                delete_set,
                k=100,
                retrieved_videos=app.retrieved_videos[device],
                normalizing_sum=app.normalizing_sum[device],
                remove=app.low_visual_indices[device],
            )
        )
    except UnidentifiedImageError:
        raise HTTPException(status_code=400, detail="Invalid image file.")
    finally:
        os.remove(temp_path)

    return results


# ---------------------------------------------------------------------------
# Delete / restore endpoints
# ---------------------------------------------------------------------------


def _resolve_image_path(device: str, image_path: str) -> str:
    """Resolve image path, adding extension if missing."""
    if image_path.endswith((".jpg", ".mp4")):
        return image_path
    for ext in (".jpg", ".mp4"):
        if os.path.exists(f"{DIR}/{device}/{image_path}{ext}"):
            return f"{image_path}{ext}"
    raise HTTPException(status_code=404, detail="Image not found")


@app.delete("/delete-image")
def delete_image(
    request: DeleteImageRequest,
    device: str,
    access_level: Annotated[AccessLevel, Depends(auth_dependency)] = AccessLevel.NONE,
    session: Session = Depends(get_session),
):
    _require_owner_or_admin(access_level)
    original = _resolve_image_path(device, request.image_path)
    _bulk_delete(session, [original], device)


@app.delete("/delete-images")
def delete_images(
    request: DeleteImagesRequest,
    device: str,
    access_level: Annotated[AccessLevel, Depends(auth_dependency)] = AccessLevel.NONE,
    session: Session = Depends(get_session),
):
    _require_owner_or_admin(access_level)
    paths = [_resolve_image_path(device, p) for p in request.image_paths]
    _bulk_delete(session, paths, device)


@app.get("/get-deleted-images")
def get_deleted_images(
    device: str,
    access_level: Annotated[AccessLevel, Depends(auth_dependency)] = AccessLevel.NONE,
    session: Session = Depends(get_session),
):
    _require_owner_or_admin(access_level)

    deleted_list = list(
        ImageRecord.find(
            session, deleted=True, device=device, sort="image_path", sort_desc=True
        )
    )

    now_ms = datetime.now(timezone.utc).timestamp() * 1000
    threshold = now_ms - 30 * 24 * 60 * 60 * 1000  # 30 days

    final_list = []
    collection = app.features[device][SEARCH_MODEL].collection
    assert collection is not None, "Collection not initialized"

    for image in deleted_list:
        full_path = os.path.join(DIR, device, image.image_path)
        if not os.path.exists(full_path):
            continue
        if image.delete_time and image.delete_time < threshold:
            remove_physical_image(device, image.image_path, collection, session)
        else:
            final_list.append(image)

    return final_list


@app.post("/restore-image")
def restore_image(
    request: DeleteImageRequest,
    device: str,
    access_level: Annotated[AccessLevel, Depends(auth_dependency)] = AccessLevel.NONE,
    session: Session = Depends(get_session),
):
    _require_owner_or_admin(access_level)
    session.execute(
        update(ImageModel)
        .where(ImageModel.image_path == request.image_path)
        .where(ImageModel.device == device)
        .values(deleted=False, delete_time=None)
    )
    session.flush()


@app.delete("/force-delete-image")
def force_delete_image(
    request: DeleteImageRequest,
    device: str,
    access_level: Annotated[AccessLevel, Depends(auth_dependency)] = AccessLevel.NONE,
    session: Session = Depends(get_session),
):
    _require_owner_or_admin(access_level)
    collection = app.features[device][SEARCH_MODEL].collection
    assert collection is not None, "Collection not initialized"
    remove_physical_image(device, request.image_path, collection, session)


@app.delete("/force-delete-images")
def force_delete_images(
    request: DeleteImagesRequest,
    device: str,
    access_level: Annotated[AccessLevel, Depends(auth_dependency)] = AccessLevel.NONE,
    session: Session = Depends(get_session),
):
    _require_owner_or_admin(access_level)
    collection = app.features[device][SEARCH_MODEL].collection
    assert collection is not None, "Collection not initialized"
    for image_path in request.image_paths:
        remove_physical_image(device, image_path, collection, session)


# ---------------------------------------------------------------------------
# Segment processing
# ---------------------------------------------------------------------------


def process_segments(session: Session, date: str, device: str):
    # Segment IDs needing activity description
    blank_ids = set(
        ImageRecord.distinct(
            session, "segment_id", date=date, deleted=False, device=device, activity=""
        )
    )
    unclear_ids = set(
        ImageRecord.distinct(
            session,
            "segment_id",
            date=date,
            deleted=False,
            device=device,
            activity="Unclear",
        )
    )
    segment_ids = list(blank_ids | unclear_ids)

    print(f"Processing {len(segment_ids)} segments for date {date}.")
    all_summaries = _get_last_n_summaries(session, date, device, n=10)

    for _, segment_id in tqdm(
        enumerate(segment_ids), total=len(segment_ids), desc="Processing segments"
    ):
        if segment_id is None:
            continue

        thumbnails = [
            img.thumbnail
            for img in ImageRecord.find(
                session,
                segment_id=segment_id,
                deleted=False,
                device=device,
                sort="image_path",
                sort_desc=False,
            )
        ]

        new_description = describe_segment_task.delay(
            device, date, thumbnails, segment_id
        )
        all_summaries = [*all_summaries, new_description][-10:]

        DaySummaryRecord.upsert(session, date=date, device=device, updated=True)


@app.get("/process-date")
def process_date(
    date: str,
    device: str,
    reset: bool,
    background_tasks: BackgroundTasks,
    access_level: Annotated[AccessLevel, Depends(auth_dependency)] = AccessLevel.NONE,
    session: Session = Depends(get_session),
):
    _require_any_access(access_level)

    DaySummaryRecord.upsert(session, date=date, device=device, updated=True)

    if reset:
        session.execute(
            update(ImageModel)
            .where(ImageModel.date == date)
            .where(ImageModel.deleted == False)
            .where(ImageModel.device == device)
            .values(
                activity="",
                activity_description="",
                activity_confidence="",
                segment_id=None,
            )
        )
        session.flush()

    deleted_set = set(
        ImageRecord.distinct(session, "image_path", deleted=True, device=device)
    )
    load_all_segments(
        device, date, app.features, deleted_set | app.images_with_low_density
    )

    return {"message": f"Processing segments for date {date} in background."}


# ---------------------------------------------------------------------------
# Day summary
# ---------------------------------------------------------------------------


@app.get("/day-summary", response_model=DaySummary)
def get_day_summary(
    date: str,
    device: str,
    user=Depends(get_user),
    access_level: Annotated[AccessLevel, Depends(auth_dependency)] = AccessLevel.NONE,
    session: Session = Depends(get_session),
):
    return DaySummary(
        device=device, date=date, segments=[], summary_text="", updated=False
    )

    _require_any_access(access_level)

    if not date:
        raise HTTPException(status_code=400, detail="Date is required.")

    day_summary = DaySummaryRecord.find_one(filter={"date": date, "device": device})
    if day_summary and not day_summary.updated:
        return day_summary

    summary = DaySummary(
        device=device, date=date, segments=[], summary_text="", updated=False
    )
    summary.segments = create_day_timeline(app, device, date)
    if not summary.segments:
        raise HTTPException(status_code=404, detail="No segments found for this date.")

    summary = summarize_day_by_text(summary)
    my_targets = user.goal_targets or DEFAULT_TARGETS

    summary = summarize_lifelog_by_day(
        summary, app.features[device][SEARCH_MODEL], my_targets
    )

    DaySummaryRecord.upsert(
        session, date=date, device=device, **summary.model_dump(by_alias=True)
    )

    return summary


# ---------------------------------------------------------------------------
# Targets
# ---------------------------------------------------------------------------


@app.get("/get-targets")
def get_targets(
    user=Depends(get_user),
    access_level: Annotated[AccessLevel, Depends(auth_dependency)] = AccessLevel.NONE,
):
    _require_any_access(access_level)
    return user.goal_targets or DEFAULT_TARGETS


@app.post("/update-targets")
def update_targets(
    targets: List[CustomTarget],
    user=Depends(get_user),
    access_level: Annotated[AccessLevel, Depends(auth_dependency)] = AccessLevel.NONE,
):
    _require_owner_or_admin(access_level)
    targets = targets or DEFAULT_TARGETS
    user.goal_targets = targets
    User.update_one({"username": user.username}, {"$set": {"goal_targets": targets}})
    return {"message": "Targets updated successfully."}


# ---------------------------------------------------------------------------
# Segment activity
# ---------------------------------------------------------------------------


@app.post("/change-segment-activity")
async def change_segment_activity(
    request: ChangeSegmentActivityRequest,
    device: str,
    access_level: Annotated[AccessLevel, Depends(auth_dependency)] = AccessLevel.NONE,
    session: Session = Depends(get_session),
):
    _require_owner_or_admin(access_level)

    segment = ImageRecord.find_one(
        session, segment_id=request.segment_id, device=device, date=request.date
    )
    if not segment or segment.segment_id is None:
        raise HTTPException(status_code=404, detail="Segment not found")

    all_summaries = _get_last_n_summaries(
        session, segment.date, device, n=10, segment_id_lt=request.segment_id
    )

    thumbnails = [
        img.thumbnail
        for img in ImageRecord.find(
            session,
            segment_id=segment.segment_id,
            date=request.date,
            deleted=False,
            device=device,
            sort="image_path",
            sort_desc=False,
        )
    ]

    new_description = describe_segment_task.delay(
        device,
        request.date,
        thumbnails,
        segment.segment_id,
        extra_info=[
            f"The previous activity descriptions were: {', '.join(all_summaries)}.",
            f"Here is the provided activity information from the camera viewer: {request.new_activity_info}. Incorporate this into the description.",
        ],
    )

    session.execute(
        update(ImageModel)
        .where(ImageModel.segment_id == segment.segment_id)
        .where(ImageModel.device == device)
        .where(ImageModel.date == request.date)
        .values(
            activity=request.new_activity_info, activity_description=new_description
        )
    )
    session.flush()

    DaySummaryRecord.upsert(session, date=request.date, device=device, updated=True)


# ---------------------------------------------------------------------------
# Face endpoints
# ---------------------------------------------------------------------------


@app.post("/get-faces", response_model=List[LifelogImage])
def get_faces(
    files: List[UploadFile],
    device: str,
    access_level: Annotated[AccessLevel, Depends(auth_dependency)] = AccessLevel.NONE,
    session: Session = Depends(get_session),
):
    _require_any_access(access_level)

    collection = app.features[device]["faces"].collection
    assert collection is not None, "Face collection not initialized"

    image_paths = search_for_faces(collection, files)
    return list(
        ImageRecord.find(
            session,
            device=device,
            deleted=False,
            sort="timestamp",
            sort_desc=True,
            # image_path__in handled via find_by_paths below
        )
    )
    # NOTE: add image_path__in filter support to ImageRecord.find() for this endpoint


@app.put("/add-to-whitelist")
def add_to_whitelist(
    files: List[UploadFile],
    device: str,
    name: str,
    access_level: Annotated[AccessLevel, Depends(auth_dependency)] = AccessLevel.NONE,
):
    _require_owner_or_admin(access_level)
    add_face_to_whitelist(device, name, files)


@app.get("/get-whitelist", response_model=List[WhitelistEntry])
def get_whitelist(
    device: str,
    access_level: Annotated[AccessLevel, Depends(auth_dependency)] = AccessLevel.NONE,
):
    _require_owner_or_admin(access_level)

    collection = app.features[device]["faces"].collection
    assert collection is not None, "Face collection not initialized"
    device_obj = Device.find_one({"device_id": device})
    assert device_obj is not None, "Device not found"

    return [
        {
            "name": e.name,
            "images": [f"data:image/jpeg;base64, {img}" for img in e.cropped[:2]],
        }
        for e in device_obj.whitelist
    ]


@app.delete("/remove-from-whitelist")
def remove_from_whitelist(
    device: str,
    name: str,
    access_level: Annotated[AccessLevel, Depends(auth_dependency)] = AccessLevel.NONE,
):
    _require_owner_or_admin(access_level)

    device_obj = Device.find_one({"device_id": device})
    assert device_obj is not None, "Device not found"
    new_whitelist = [e for e in device_obj.whitelist if e.name != name]
    Device.update_one(
        {"device_id": device},
        {"$set": {"whitelist": [e.model_dump() for e in new_whitelist]}},
    )
    return {"message": f"Removed {name} from whitelist."}


@app.post("/segment-image")
def segment_image(file: UploadFile):
    visualised_base64, masks_data, bbox_list = segment_image_with_sam(
        Image.open(file.file)
    )
    return {
        "visualisation": f"data:image/jpeg;base64, {visualised_base64}",
        "masks": masks_data,
        "bboxes": bbox_list,
    }


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    uvicorn.run("main:app", host="0.0.0.0", port=LOCAL_PORT, reload=True)

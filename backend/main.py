from constants import DIR, LOCAL_PORT

import os
from dotenv import load_dotenv
import asyncio
import time
from datetime import datetime, timezone
import logging

from dependencies import CamelCaseModel
from app_types import CustomFastAPI, CustomTarget, DaySummary
from auth.types import AccessLevel, User
from day_summary_tasks import (
    DEFAULT_TARGETS,
    _LIVE_THRESHOLD_MINUTES,
    _day_summary_bg,
    _get_last_n_summaries,
    _process_date_bg,
    _text_summary_bg,
)
from scripts.summary import summarize_lifelog_by_day, update_dirty_segments

from fastapi import BackgroundTasks, Depends, HTTPException, Request, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from contextlib import asynccontextmanager
from typing import Annotated, List

from sqlalchemy import func, update, select
from sqlalchemy.orm import Session
from database import close_db, init_db, get_session
from database.types import DaySummaryRecord, ImageRecord
from database.models import Image as ImageModel

from biometrics import mqtt_consumer
from auth import auth_app, _require_admin, _require_any_access, _require_owner
from auth.auth_models import auth_dependency, get_user
from tasks import describe_segment_task
from pipelines.all import process_video
from preprocess import load_features
from scripts.utils import CustomFormatter
from settings.utils import create_device

from settings import control_app
from ingest import app as ingest_app
from apis.explore import app as explore_app
from apis.location import app as location_app
from apis.browse import app as browse_app
from apis.images import app as image_app
from apis.annotations import app as annotation_app
from apis.retrieval import app as retrieval_app
from apis.face import app as face_app
from apis.delete import app as delete_app
from apis.notifications import app as notifications_app
from apis.status import app as status_app


load_dotenv()

ch = logging.StreamHandler()
ch.setFormatter(CustomFormatter())

logging.basicConfig(
    level=logging.INFO,
    force=True,
    handlers=[ch]
)

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Request models
# ---------------------------------------------------------------------------
class ChangeSegmentActivityRequest(CamelCaseModel):
    date: str
    segment_id: int
    new_activity_info: str


# ---------------------------------------------------------------------------
# Lifespan
# ---------------------------------------------------------------------------

@asynccontextmanager
async def lifespan(app: CustomFastAPI):
    print("Starting up server...")
    init_db()
    app.features = load_features(app)
    mqtt_task = asyncio.create_task(mqtt_consumer())
    yield
    close_db()
    mqtt_task.cancel()
    try:
        await asyncio.wait_for(mqtt_task, timeout=5.0)
    except (asyncio.CancelledError, asyncio.TimeoutError):
        print("MQTT consumer safely stopped.")


# ---------------------------------------------------------------------------
# App setup
# ---------------------------------------------------------------------------

app = CustomFastAPI(lifespan=lifespan)
app.mount("/auth", auth_app)
app.mount("/controls", control_app)
app.mount("/ingest", ingest_app)
app.mount("/explore", explore_app)
app.mount("/browse", browse_app)
app.mount("/location", location_app)
app.mount("/images", image_app)
app.mount("/annotations", annotation_app)
app.mount("/retrieval", retrieval_app)
app.mount("/face", face_app)
app.mount("/delete", delete_app)
app.mount("/notify", notifications_app)
app.mount("/status", status_app)

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
    max_age=3600,
)

def _get_time_color(process_time: float) -> str:
    if process_time < 0.5:
        return "\x1b[32m"
    elif process_time < 1.0:
        return "\x1b[33m"
    else:
        return "\x1b[31m"

@app.middleware("http")
async def add_process_time_header(request: Request, call_next):
    start_time: float = time.perf_counter()
    response = await call_next(request)
    process_time: float = time.perf_counter() - start_time

    response.headers["X-Process-Time"] = str(process_time)
    request.scope["process_time"] = f"{process_time:.4f}s"

    color = _get_time_color(process_time)
    reset = "\x1b[0m"
    logger.info(
        f"{request.method} {request.url.path} {color}[{process_time:.4f}s]{reset}"
    )

    return response


# ---------------------------------------------------------------------------
# Root
# ---------------------------------------------------------------------------

@app.get("/")
async def root():
    return {"message": "Hello, World!"}

@app.get("/_debug/tasks")
async def get_running_tasks():
    tasks = asyncio.all_tasks()
    task_list = []

    for i, task in enumerate(tasks):
        if task == asyncio.current_task():
            continue

        stack = task.get_stack()
        formatted_stack = [
            f"{f.f_code.co_filename}:{f.f_lineno} in {f.f_code.co_name}"
            for f in stack
        ]

        task_list.append({
            "task_id": i,
            "name": task.get_name(),
            "coro": str(task.get_coro()),
            "current_stack": formatted_stack
        })

    return {"running_tasks_count": len(task_list), "tasks": task_list}


# ---------------------------------------------------------------------------
# Upload endpoints
# ---------------------------------------------------------------------------

@app.put("/upload-video", deprecated=True)
async def upload_video(
    file: UploadFile,
    background_tasks: BackgroundTasks,
    device: str
):
    file_name = file.filename
    if not file_name:
        raise HTTPException(status_code=400, detail="Filename is required.")

    timestamp = datetime.strptime(file_name.split(".")[0], "%Y%m%d_%H%M%S_%Z")
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

    background_tasks.add_task(process_video, device, date, file_name)
    return {"message": "Video uploaded successfully."}

# ---------------------------------------------------------------------------
# App navigation endpoints
# ---------------------------------------------------------------------------

@app.get("/get-devices", response_model=List[str],
         description="Get a list of content a user has access to. Admins get all.")
def get_devices(user=Depends(get_user)):
    return [d.device_id for d in user.devices]

@app.get("/get-all-dates")
def get_all_dates(
    device: str,
    access_level: Annotated[AccessLevel, Depends(auth_dependency)] = AccessLevel.NONE,
    session: Session = Depends(get_session)
):
    _require_any_access(access_level)

    all_dates = session.execute(
        select(ImageModel.date).where(ImageModel.device == device).distinct()
    ).scalars().all()
    return sorted([d for d in all_dates if d])


@app.get("/create-device")
def create_device_endpoint(
    device: str,
    access_level: Annotated[AccessLevel, Depends(auth_dependency)] = AccessLevel.NONE,
    session: Session = Depends(get_session)
):
    _require_admin(access_level)
    create_device(session, device)
    return {"message": f"Device {device} created successfully."}


# ---------------------------------------------------------------------------
# Segment processing
# ---------------------------------------------------------------------------

@app.post("/resync-day")
def resync_day(
    date: str,
    device: str,
    access_level: Annotated[AccessLevel, Depends(auth_dependency)] = AccessLevel.NONE,
):
    """Re-segment from first gap, skip LLM for already-annotated segments."""
    _require_owner(access_level)
    from tasks import resync_day_task
    resync_day_task.delay(device, date)
    return {"message": f"Resync queued for {device}/{date}"}


@app.get("/process-date")
def process_date(
    date: str,
    device: str,
    resegment: bool = False,
    reannotate: bool = False,
    background_tasks: BackgroundTasks = None,  # type: ignore
    access_level: Annotated[AccessLevel, Depends(auth_dependency)] = AccessLevel.NONE,
    session: Session = Depends(get_session),
):
    _require_any_access(access_level)

    if not resegment and not reannotate:
        existing = DaySummaryRecord.find_one(filter={"date": date, "device": device})
        if existing and getattr(existing, "processing", False):
            return {"message": "Already processing.", "processing": True}

    if resegment or reannotate:
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
        session.commit()
        session.flush()
        logger.info("Reset segments for date %s and device %s.", date, device)

    DaySummaryRecord.update_one(
        {"date": date, "device": device},
        data={"$set": {"processing": True, "segments": [], "summary_text": "", "dirty_segment_ids": [], "text_summary_stale": True}},
        upsert=True,
    )
    background_tasks.add_task(_process_date_bg, device, date, reannotate)
    return {"message": f"Processing segments for date {date} in background.", "processing": True}


# ---------------------------------------------------------------------------
# Day summary
# ---------------------------------------------------------------------------

@app.get("/day-summary", response_model=DaySummary)
def get_day_summary(
    date: str,
    device: str,
    background_tasks: BackgroundTasks = None,  # type: ignore
    user=Depends(get_user),
    access_level: Annotated[AccessLevel, Depends(auth_dependency)] = AccessLevel.NONE,
    session: Session = Depends(get_session),
):
    _require_any_access(access_level)

    if not date:
        raise HTTPException(status_code=400, detail="Date is required.")

    number_of_images = session.execute(
        select(func.count(ImageModel.id)).where(
            ImageModel.date == date,
            ImageModel.device == device,
            ImageModel.deleted == False,
        )
    ).scalar_one()

    if number_of_images == 0:
        return None

    last_image = session.execute(
        select(ImageModel).where(
            ImageModel.date == date,
            ImageModel.device == device,
            ImageModel.deleted == False,
        ).order_by(ImageModel.image_path.desc())
    ).scalars().first()
    last_image_time = last_image.timestamp if last_image else None

    today = datetime.now().strftime("%Y-%m-%d")
    is_live = False
    if date == today and last_image_time is not None:
        ts = last_image_time.replace(tzinfo=timezone.utc) if last_image_time.tzinfo is None else last_image_time
        age = (datetime.now(timezone.utc) - ts).total_seconds() / 60
        is_live = age < _LIVE_THRESHOLD_MINUTES

    day_summary = DaySummaryRecord.find_one(filter={"date": date, "device": device})

    if (
        day_summary
        and day_summary.segments
        and not getattr(day_summary, "updated", False)
        and not getattr(day_summary, "dirty_segment_ids", [])
        and not getattr(day_summary, "text_summary_stale", False)
        and not getattr(day_summary, "processing", False)
        and (is_live or (
            day_summary.number_of_images == number_of_images
            and day_summary.last_image_time == last_image_time
        ))
    ):
        logger.info("day-summary cache hit for %s/%s", device, date)
        cached = DaySummary.model_validate(day_summary.__dict__)
        cached.is_live = is_live
        return cached

    if getattr(day_summary, "processing", False):
        logger.info("day-summary: background task already running for %s/%s", device, date)
        if day_summary and day_summary.segments:
            partial = DaySummary.model_validate(day_summary.__dict__)
        else:
            partial = DaySummary(device=device, date=date, segments=[], summary_text="")
        partial.processing = True
        partial.is_live = is_live
        partial.number_of_images = number_of_images
        partial.last_image_time = last_image_time  # type: ignore
        return partial

    dirty_ids: list[int] = list(getattr(day_summary, "dirty_segment_ids", []) or [])
    text_stale: bool = bool(getattr(day_summary, "text_summary_stale", True))

    need_full_rebuild = (
        day_summary is None
        or not day_summary.segments
        or (not is_live and day_summary.number_of_images != number_of_images)
    )

    if need_full_rebuild:
        logger.info("Full day-summary rebuild (background) for %s/%s", device, date)
        my_targets = user.goal_targets or DEFAULT_TARGETS
        target_dicts = [{"name": t.name, "action_type": t.action_type.value, "query_prompt": t.query_prompt} for t in my_targets]
        DaySummaryRecord.update_one(
            {"date": date, "device": device},
            data={"$set": {"processing": True, "date": date, "device": device}},
            upsert=True,
        )
        background_tasks.add_task(_day_summary_bg, device, date, target_dicts)
        return DaySummary(
            device=device, date=date, segments=[],
            summary_text="", processing=True, is_live=is_live,
            number_of_images=number_of_images, last_image_time=last_image_time,  # type: ignore
        )

    if dirty_ids:
        logger.info(
            "Incremental segment patch for %s/%s (dirty: %s)",
            device, date, dirty_ids,
        )
        summary = DaySummary.model_validate(day_summary.__dict__)
        summary.segments = update_dirty_segments(
            session, device, date, dirty_ids, summary.segments
        )
        summary.dirty_segment_ids = []
    else:
        summary = DaySummary.model_validate(day_summary.__dict__)

    # Determine if LLM text needs regeneration.
    # For live days: throttle to at most once per hour.
    _last_text_gen = getattr(day_summary, "text_summary_generated_at", None)
    if _last_text_gen and _last_text_gen.tzinfo is None:
        _last_text_gen = _last_text_gen.replace(tzinfo=timezone.utc)
    _text_age_hours = (
        (datetime.now(timezone.utc) - _last_text_gen).total_seconds() / 3600
        if _last_text_gen else float("inf")
    )
    needs_text_regen = text_stale or (is_live and _text_age_hours >= 1.0)

    if needs_text_regen:
        reason = "stale" if text_stale else "hourly live refresh"
        logger.info("Text summary (%s) for %s/%s — dispatching background LLM task", reason, device, date)
        summary.processing = True
        DaySummaryRecord.update_one(
            {"date": date, "device": device},
            data={"$set": {**summary.model_dump(), "dirty_segment_ids": [], "processing": True}},
            upsert=True,
        )
        background_tasks.add_task(_text_summary_bg, device, date, is_live)
        summary.is_live = is_live
        summary.number_of_images = number_of_images
        summary.last_image_time = last_image_time  # type: ignore
        return summary

    my_targets = user.goal_targets or DEFAULT_TARGETS
    summary = summarize_lifelog_by_day(session, summary, my_targets)

    from database.models import BioDayStats as BioDayStatsModel
    bio = session.execute(
        select(BioDayStatsModel).where(
            BioDayStatsModel.device_id == device,
            BioDayStatsModel.date == date,
        )
    ).scalars().first()
    if bio:
        summary.avg_hr = bio.avg_hr
        summary.resting_hr = bio.resting_hr
        summary.max_hr = bio.max_hr
        summary.rmssd = bio.rmssd
        summary.step_count = bio.step_count
        summary.sleep_start = bio.sleep_start  # type: ignore
        summary.sleep_end = bio.sleep_end  # type: ignore
        summary.sleep_minutes = bio.sleep_minutes

    summary.number_of_images = number_of_images
    summary.last_image_time = last_image_time  # type: ignore
    summary.is_live = is_live
    summary.dirty_segment_ids = []
    summary.updated = False
    summary.processing = False

    DaySummaryRecord.update_one(
        {"date": date, "device": device},
        data={"$set": {**summary.model_dump(), "dirty_segment_ids": [], "text_summary_stale": False, "processing": False}},
        upsert=True,
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
    _require_owner(access_level)
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
    _require_owner(access_level)

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

    describe_segment_task.delay(
        device,
        request.date,
        thumbnails,
        segment.segment_id,
        extra_info=[
            f"The previous activity descriptions were: {', '.join(all_summaries)}.",
            f"Here is the provided activity information from the camera viewer: {request.new_activity_info}. Incorporate this into the description.",
        ],
    )

    DaySummaryRecord.update_one(
        {
            "date": request.date,
            "device": device,
        },
        data={"$set": {"updated": True}},
    )


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="0.0.0.0", port=LOCAL_PORT, reload=True)

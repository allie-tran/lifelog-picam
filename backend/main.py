import asyncio
import base64
from contextvars import ContextVar
import io
import os
from contextlib import asynccontextmanager
from datetime import datetime, timezone
import time
from typing import Annotated, List, Optional

from PIL import Image
from dotenv import load_dotenv
from fastapi import BackgroundTasks, Depends, HTTPException, Request, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import func, update
from sqlalchemy.orm import Session
from tqdm.auto import tqdm

from biometrics import mqtt_consumer
from app_types import ActionType, CustomFastAPI, CustomTarget, DaySummary
from auth import auth_app, _require_admin, _require_any_access, _require_owner
from auth.auth_models import auth_dependency, get_user
from auth.types import AccessLevel, User
from constants import DIR, LOCAL_PORT
from database import close_db, init_db, get_session, engine as _db_engine
from database.types import DaySummaryRecord, ImageRecord
from database.models import Image as ImageModel, Device
from dependencies import CamelCaseModel
from tasks import describe_segment_task
from ingest import app as ingest_app
from pipelines.all import process_video
from pipelines.hourly import update_app
from preprocess import  load_features
from scripts.segmentation import load_all_segments
from scripts.summary import (
    create_day_timeline,
    update_dirty_segments,
    summarize_day_by_text,
    summarize_lifelog_by_day,
)
from scripts.utils import CustomFormatter, get_thumbnail_path
from settings import control_app
from settings.utils import create_device
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

from sqlalchemy import select, desc, update
from datetime import datetime
import logging

ch = logging.StreamHandler()
ch.setFormatter(CustomFormatter())

# Inject it straight into the root configuration
logging.basicConfig(
    level=logging.INFO,
    force=True,
    handlers=[ch]  # <-- Force the root logger to use your custom colored handler
)

logger = logging.getLogger(__name__)  # No extra addHandler() needed!


# ---------------------------------------------------------------------------
# Request models
# ---------------------------------------------------------------------------
class ChangeSegmentActivityRequest(CamelCaseModel):
    date: str
    segment_id: int
    new_activity_info: str


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

load_dotenv()
picam_username = os.getenv("PICAM_USERNAME", "default_user")


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


def _day_summary_bg(device: str, date: str, target_dicts: list) -> None:
    """Background: full day-summary rebuild (segmentation → timeline → LLM → CLIP)."""
    from sqlalchemy.orm import Session as _Session
    try:
        with _Session(_db_engine) as session:
            load_all_segments(session, device, date, skip_annotations=False)
            segments = create_day_timeline(session, device, date)
            if not segments:
                logger.warning("_day_summary_bg: no segments found for %s/%s", device, date)
                DaySummaryRecord.update_one(
                    {"date": date, "device": device},
                    data={"$set": {"processing": False}},
                    upsert=True,
                )
                return

            targets = [CustomTarget(name=t["name"], action_type=ActionType(t["action_type"]), query_prompt=t["query_prompt"]) for t in target_dicts]
            summary = DaySummary(
                device=device, date=date, segments=segments,
                summary_text="", updated=False, dirty_segment_ids=[], text_summary_stale=True,
            )

            # Compute is_live inside the task
            last_img_ts = segments[-1].end_time if segments else None
            _today = datetime.now().strftime("%Y-%m-%d")
            _is_live = False
            if date == _today and last_img_ts is not None:
                _ts = last_img_ts.replace(tzinfo=timezone.utc) if last_img_ts.tzinfo is None else last_img_ts
                _is_live = (datetime.now(timezone.utc) - _ts).total_seconds() / 60 < _LIVE_THRESHOLD_MINUTES

            if not _is_live:
                summary = summarize_day_by_text(session, summary)
                summary.text_summary_stale = False
                try:
                    from scripts.novelty import generate_unique_day_highlight
                    from scripts.notify import notify_day_complete, notify_novelty
                    highlight, novel_ids = generate_unique_day_highlight(session, device, date)
                    summary.unique_highlight = highlight
                    summary.novelty_segments = novel_ids
                    notify_day_complete(session, device, date, summary.summary_text)
                    if highlight:
                        rep_thumb = None
                        if novel_ids:
                            _rep = session.execute(
                                select(ImageModel.thumbnail)
                                .where(
                                    ImageModel.device == device,
                                    ImageModel.segment_id == novel_ids[0],
                                    ImageModel.date == date,
                                    ImageModel.deleted == False,
                                )
                                .limit(1)
                            ).scalars().first()
                            rep_thumb = _rep
                        notify_novelty(session, device, date, highlight, rep_thumb)
                    session.commit()
                except Exception as _nve:
                    logger.warning("_day_summary_bg: novelty step failed for %s/%s: %s", device, date, _nve)

            summary = summarize_lifelog_by_day(session, summary, targets)

            from database.models import BioDayStats as _BioDayStats
            bio = session.execute(
                select(_BioDayStats).where(_BioDayStats.device_id == device, _BioDayStats.date == date)
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

            n = session.execute(
                select(func.count(ImageModel.id)).where(
                    ImageModel.date == date, ImageModel.device == device, ImageModel.deleted == False,
                )
            ).scalar_one()
            last_img = session.execute(
                select(ImageModel).where(
                    ImageModel.date == date, ImageModel.device == device, ImageModel.deleted == False,
                ).order_by(ImageModel.image_path.desc())
            ).scalars().first()

            summary.number_of_images = n
            summary.last_image_time = last_img.timestamp if last_img else None  # type: ignore
            summary.dirty_segment_ids = []
            summary.updated = False
            summary.processing = False

            DaySummaryRecord.update_one(
                {"date": date, "device": device},
                data={"$set": {**summary.model_dump(), "dirty_segment_ids": [], "text_summary_stale": False, "processing": False}},
                upsert=True,
            )
            logger.info("_day_summary_bg complete for %s/%s", device, date)
    except Exception as exc:
        logger.error("_day_summary_bg failed for %s/%s: %s", device, date, exc)
        DaySummaryRecord.update_one(
            {"date": date, "device": device},
            data={"$set": {"processing": False}},
            upsert=True,
        )


def _text_summary_bg(device: str, date: str) -> None:
    """Background: regenerate only the LLM text summary for an existing day record."""
    from sqlalchemy.orm import Session as _Session
    try:
        with _Session(_db_engine) as session:
            existing = DaySummaryRecord.find_one(filter={"date": date, "device": device})
            if not existing or not existing.segments:
                return
            summary = DaySummary.model_validate(existing.__dict__)
            summary = summarize_day_by_text(session, summary)
            summary.text_summary_stale = False
            try:
                from scripts.novelty import generate_unique_day_highlight
                from scripts.notify import notify_day_complete, notify_novelty
                highlight, novel_ids = generate_unique_day_highlight(session, device, date)
                summary.unique_highlight = highlight
                summary.novelty_segments = novel_ids
                notify_day_complete(session, device, date, summary.summary_text)
                if highlight:
                    rep_thumb = None
                    if novel_ids:
                        _rep = session.execute(
                            select(ImageModel.thumbnail)
                            .where(
                                ImageModel.device == device,
                                ImageModel.segment_id == novel_ids[0],
                                ImageModel.date == date,
                                ImageModel.deleted == False,
                            )
                            .limit(1)
                        ).scalars().first()
                        rep_thumb = _rep
                    notify_novelty(session, device, date, highlight, rep_thumb)
                session.commit()
            except Exception as _nve:
                logger.warning("_text_summary_bg: novelty step failed for %s/%s: %s", device, date, _nve)
            DaySummaryRecord.update_one(
                {"date": date, "device": device},
                data={"$set": {
                    "summary_text": summary.summary_text,
                    "text_summary_stale": False,
                    "unique_highlight": summary.unique_highlight,
                    "novelty_segments": summary.novelty_segments,
                    "processing": False,
                }},
                upsert=True,
            )
            logger.info("_text_summary_bg complete for %s/%s", device, date)
    except Exception as exc:
        logger.error("_text_summary_bg failed for %s/%s: %s", device, date, exc)
        DaySummaryRecord.update_one(
            {"date": date, "device": device},
            data={"$set": {"processing": False}},
            upsert=True,
        )


def _process_date_bg(device: str, date: str, reannotate: bool) -> None:
    """Background: run segmentation for a given date."""
    from sqlalchemy.orm import Session as _Session
    try:
        with _Session(_db_engine) as session:
            load_all_segments(session, device, date, skip_annotations=not reannotate)
        logger.info("_process_date_bg complete for %s/%s", device, date)
    except Exception as exc:
        logger.error("_process_date_bg failed for %s/%s: %s", device, date, exc)
    finally:
        DaySummaryRecord.update_one(
            {"date": date, "device": device},
            data={"$set": {"processing": False}},
            upsert=True,
        )


def _get_last_n_summaries(
    session: Session,
    date: str,
    device: str,
    n: int = 10,
    segment_id_lt: Optional[int] = None,
) -> list[str]:
    """Get the last n activity descriptions for context, optionally filtered by segment_id."""

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
)

def _get_time_color(process_time: float) -> str:
    """Return a color code based on the process time."""
    if process_time < 0.5:
        return "\x1b[32m"  # Green for fast responses
    elif process_time < 1.0:
        return "\x1b[33m"  # Yellow for moderate responses
    else:
        return "\x1b[31m"  # Red for slow responses

@app.middleware("http")
async def add_process_time_header(request: Request, call_next):

    start_time: float = time.perf_counter()
    response = await call_next(request)
    process_time: float = time.perf_counter() - start_time

    response.headers["X-Process-Time"] = str(process_time)

    # Keep the raw plain text in the scope if other filters need it
    request.scope["process_time"] = f"{process_time:.4f}s"

    # Colorize the brackets and the time string right here inside the logger line!
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
        # Skip this current request task to avoid clutter
        if task == asyncio.current_task():
            continue

        # Extract where the task is currently halted
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
    # device: str = Depends(get_device_from_headers),
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

    background_tasks.add_task(
        process_video,
        device,
        date,
        file_name,
    )
    return {"message": "Video uploaded successfully."}


@app.post("/update-app", deprecated=True)
async def update_app_endpoint(
    job_id: str,
    background_tasks: BackgroundTasks,
    session: Session = Depends(get_session),
):
    background_tasks.add_task(update_app, session, app, job_id=job_id)
    return {"message": "App update scheduled."}

# ---------------------------------------------------------------------------
# App navigation endpoints
# ---------------------------------------------------------------------------
@app.get("/get-devices", response_model=List[str],
         description="Get a list of content a user has access to. Admins get all.")
def get_devices(user=Depends(get_user),
                session: Session = Depends(get_session)):
    if user.is_admin:
        return [d.device_id for d in session.execute(select(Device)).scalars().all()]
    return [d.device_id for d in user.devices]

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

@app.get("/create-device")
def create_device_endpoint(
    device: str,
    access_level: Annotated[AccessLevel, Depends(auth_dependency)] = AccessLevel.NONE,
    session: Session = Depends(get_session)
):
    _require_admin(access_level)
    create_device(session, device)
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

        DaySummaryRecord.update_one(
            {
                "date": date,
                "device": device,
            },
            data={"$set": {"updated": True}},
        )


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

    # Guard: skip if already processing, unless the caller is forcing a reset
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

    # Wipe cached summary so the next /day-summary triggers a full rebuild
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

_LIVE_THRESHOLD_MINUTES = 20  # day is "live" if last image arrived within this window


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

    # Determine if day is still actively being recorded
    today = datetime.now().strftime("%Y-%m-%d")
    is_live = False
    if date == today and last_image_time is not None:
        ts = last_image_time.replace(tzinfo=timezone.utc) if last_image_time.tzinfo is None else last_image_time
        age = (datetime.now(timezone.utc) - ts).total_seconds() / 60
        is_live = age < _LIVE_THRESHOLD_MINUTES

    day_summary = DaySummaryRecord.find_one(filter={"date": date, "device": device})

    # ── Fast path: cache is clean ────────────────────────────────────────────
    # For live (today) days: skip image-count/last-image checks — images arrive
    # every 10 s so those fields are always stale.  Annotations drive updates
    # via dirty_segment_ids instead.
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

    # ── Guard: background task already running — return partial immediately ──
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

    # ── Determine what work is needed ────────────────────────────────────────
    dirty_ids: list[int] = list(getattr(day_summary, "dirty_segment_ids", []) or [])
    text_stale: bool = bool(getattr(day_summary, "text_summary_stale", True))

    # For live days don't rebuild just because image count grew — unannotated
    # images don't contribute to the summary yet and dirty_segment_ids handles
    # newly completed segments.
    need_full_rebuild = (
        day_summary is None
        or not day_summary.segments
        or (not is_live and day_summary.number_of_images != number_of_images)
    )

    # ── Full rebuild: dispatch to background, return immediately ─────────────
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

    # ── Partial path: patch dirty segments (inline — fast) ───────────────────
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

    # ── LLM text summary — background when stale, skip when live ────────────
    if text_stale and not is_live:
        logger.info("Text summary stale for %s/%s — dispatching background LLM task", device, date)
        summary.processing = True
        DaySummaryRecord.update_one(
            {"date": date, "device": device},
            data={"$set": {**summary.model_dump(), "dirty_segment_ids": [], "processing": True}},
            upsert=True,
        )
        background_tasks.add_task(_text_summary_bg, device, date)
        summary.is_live = is_live
        summary.number_of_images = number_of_images
        summary.last_image_time = last_image_time  # type: ignore
        return summary
    elif text_stale and is_live:
        logger.debug("Skipping LLM text summary: day %s is still live", date)

    # ── Custom targets (CLIP analysis) — inline ──────────────────────────────
    if not is_live:
        my_targets = user.goal_targets or DEFAULT_TARGETS
        summary = summarize_lifelog_by_day(session, summary, my_targets)

    # ── Attach bio stats if available ────────────────────────────────────────
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

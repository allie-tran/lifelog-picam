import asyncio
import base64
import io
import os
from contextlib import asynccontextmanager
from datetime import datetime
from typing import Annotated, List, Optional

from PIL import Image
import uvicorn
from dotenv import load_dotenv
from fastapi import BackgroundTasks, Depends, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from sqlalchemy import update
from sqlalchemy.orm import Session
from tqdm.auto import tqdm

from biometrics import mqtt_consumer
from app_types import ActionType, CustomFastAPI, CustomTarget, DaySummary
from auth import auth_app, _require_admin, _require_any_access, _require_owner
from auth.auth_models import auth_dependency, get_user
from auth.types import AccessLevel, User
from constants import DIR, LOCAL_PORT
from database import close_db, init_db, get_session
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
    summarize_day_by_text,
    summarize_lifelog_by_day,
)
from scripts.utils import get_thumbnail_path
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

from sqlalchemy import select, desc, update
from datetime import datetime
import logging

logging.basicConfig(
    level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s",
    force=True
)


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
        await mqtt_task
    except asyncio.CancelledError:
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
    access_level: Annotated[AccessLevel, Depends(auth_dependency)] = AccessLevel.NONE,
    session: Session = Depends(get_session),
):
    _require_any_access(access_level)

    DaySummaryRecord.update_one(
        {
            "date": date,
            "device": device,
        },
        data={"$set": {"updated": True}},
        upsert=True,
    )

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
        print(f"Reset segments for date {date} and device {device}.")

    load_all_segments(session, device, date, skip_annotations=not reannotate)
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
    _require_any_access(access_level)

    if not date:
        raise HTTPException(status_code=400, detail="Date is required.")

    day_summary = DaySummaryRecord.find_one(filter={"date": date, "device": device})
    if day_summary and day_summary.segments and not day_summary.updated:
        return day_summary

    print(f"Creating day summary for date {date} and device {device}.")
    summary = DaySummary(
        device=device, date=date, segments=[], summary_text="", updated=False
    )
    summary.segments = create_day_timeline(session, device, date)
    if not summary.segments:
        raise HTTPException(status_code=404, detail="No segments found for this date.")

    summary = summarize_day_by_text(session, summary)
    my_targets = user.goal_targets or DEFAULT_TARGETS

    summary = summarize_lifelog_by_day(
        session,
        summary,
        my_targets
    )

    DaySummaryRecord.update_one(
        {
            "date": date,
            "device": device,
        },
        data={"$set": { **summary.model_dump(), "updated": False}},
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
    uvicorn.run("main:app", host="0.0.0.0", port=LOCAL_PORT, reload=True)

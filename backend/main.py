from core.config import DIR, LOCAL_PORT

import os
import subprocess
from dotenv import load_dotenv
import asyncio
import time
from datetime import datetime
import logging

from schemas import CustomFastAPI
from auth.types import AccessLevel

from fastapi import BackgroundTasks, Depends, HTTPException, Request, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.gzip import GZipMiddleware
from contextlib import asynccontextmanager
from typing import Annotated, List

from sqlalchemy import select
from sqlalchemy.orm import Session
from database import close_db, init_db, get_session
from database.models import Image as ImageModel

from integrations.biometrics import mqtt_consumer
from auth import router as auth_router, _require_admin, _require_any_access
from auth.auth_models import auth_dependency, get_user
from pipelines.all import process_video
from services.embedding import load_features
from services.utils import CustomFormatter
from settings.utils import create_device

from routers.day_summary import router as day_summary_router
from routers.ingest import router as ingest_router
from routers.explore import router as explore_router
from routers.location import router as location_router
from routers.browse import router as browse_router
from routers.images import router as images_router
from routers.annotations import router as annotations_router
from routers.retrieval import router as retrieval_router
from routers.face import router as face_router
from routers.delete import router as delete_router
from routers.notifications import router as notifications_router
from routers.status import router as status_router


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

# Sub-app routers. Prefixes preserve the original mount paths so external URLs
# (frontend + camera clients) are unchanged after the APIRouter migration.
app.include_router(auth_router, prefix="/auth", tags=["auth"])
app.include_router(ingest_router, prefix="/ingest", tags=["ingest"])
app.include_router(explore_router, prefix="/explore", tags=["explore"])
app.include_router(browse_router, prefix="/browse", tags=["browse"])
app.include_router(location_router, prefix="/location", tags=["location"])
app.include_router(images_router, prefix="/images", tags=["images"])
app.include_router(annotations_router, prefix="/annotations", tags=["annotations"])
app.include_router(retrieval_router, prefix="/retrieval", tags=["retrieval"])
app.include_router(face_router, prefix="/face", tags=["face"])
app.include_router(delete_router, prefix="/delete", tags=["delete"])
app.include_router(notifications_router, prefix="/notify", tags=["notifications"])
app.include_router(status_router, prefix="/status", tags=["status"])
# Day summary / targets / segment-activity — kept at root paths (no prefix).
app.include_router(day_summary_router, tags=["day-summary"])

# Compress JSON responses (segments, gps, day-nav) — repetitive text shrinks
# ~80-90%, the biggest win for browsing over slow connections.
app.add_middleware(GZipMiddleware, minimum_size=500)

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
        # Use an argument list (no shell) so a crafted filename can't inject commands.
        subprocess.run(
            ["ffmpeg", "-i", output_path, "-c", "copy", mp4_path,
             "-vn", "-y", "-metadata:s:v", "rotate=90"],
            check=False,
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
# Entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="0.0.0.0", port=LOCAL_PORT, reload=True)

from celery.app.task import Task
from celery.schedules import crontab
from celery.contrib.abortable import AbortableAsyncResult, AbortableTask
from celery.local import class_property
from celery.result import AsyncResult
from celery.utils.objects import FallbackContext
from celery import Celery
from celery.signals import after_setup_logger
from dotenv import load_dotenv
import logging

load_dotenv()

@after_setup_logger.connect
def setup_scripts_logger(logger, **kwargs):
    logging.getLogger("services").setLevel(logging.DEBUG)

celery = Celery(
    "picam-tasks",
    broker="redis://localhost:6379/0",
    backend="redis://localhost:6379/0",
    include=["tasks"],
)

from celery.signals import worker_ready, worker_process_init


def _connect_odm():
    """Open the mongodb-odm connection for this worker process.

    init_db() (the ODM connect) is otherwise only called from the FastAPI
    lifespan, so a celery worker had no ODM connection — any Document call
    (DaySummaryRecord.find/update_one, etc.) raised "DB connection URL is not
    provided". Connect on worker start so ODM-based tasks work off the web
    process. Idempotent enough to run under both solo and prefork pools.
    """
    try:
        from database import init_db
        init_db()
    except Exception as e:
        logging.warning("celery worker: ODM connect failed: %s", e)


@worker_process_init.connect
def _init_worker_process(**kwargs):
    # Fires in each forked child (prefork pool) — connect there so the pymongo
    # client isn't inherited across fork.
    _connect_odm()


@worker_ready.connect
def _purge_stale_tasks(sender, **kwargs):
    """Discard tasks left in Redis from a previous worker run."""
    sender.app.control.purge()
    # Solo pool runs tasks in the main process (worker_process_init may not
    # fire), so connect the ODM here too. init_db() is safe to call twice.
    _connect_odm()

celery.conf.update(
    worker_pool="solo",
    task_serializer="json",
    result_serializer="json",
    accept_content=["json"],
    task_track_started=True,
    # Per-segment annotation is a pure Gemini API call (I/O-bound, no GPU). On the
    # single solo worker N segments annotate strictly serially — the main reason a
    # fresh day is slow to process. Route it to a dedicated `llm` queue so a second
    # threads-pool worker can run many in parallel, while GPU tasks (yolo/embedding/
    # clip/face) stay on the solo worker's default `celery` queue. See run commands
    # in CLAUDE.md; the GPU worker also consumes `llm` as a fallback so annotation
    # still runs (serially) if the llm worker is down.
    task_routes={
        "tasks.describe_segment_task": {"queue": "llm"},
    },
    beat_schedule={
        # 02:00 UTC — bio aggregates for today + yesterday across all sensor devices
        "nightly-bio-stats": {
            "task": "tasks.nightly_bio_stats_all_devices",
            "schedule": crontab(hour=2, minute=0),
        },
        # 03:30 UTC — face cluster catch-up across all devices
        "nightly-face-recluster": {
            "task": "tasks.nightly_recluster_all_devices",
            "schedule": crontab(hour=3, minute=30),
        },
        # every 15 min — location assignment for any dates still missing it
        "location-update": {
            "task": "tasks.location_update_all_devices",
            "schedule": crontab(minute="*/10"),
        },
        # every 15 min — LLM status summary for recently-active devices
        "update-status-summary": {
            "task": "tasks.update_status_summary",
            "schedule": crontab(minute="*/30"),
        },
        # every 60 min — re-queue images that lost pipeline tasks after Celery restart
        "pipeline-catchup": {
            "task": "tasks.pipeline_catchup_task",
            "schedule": crontab(minute="*/60"),
            "options": {"expires": 600},
        },
        # every 15 min — re-queue segments left unannotated (grey on DayNav) by a
        # failed/orphaned describe_segment_task, so they recover within minutes
        "backfill-unannotated-segments": {
            "task": "tasks.backfill_unannotated_segments_task",
            "schedule": crontab(minute="*/15"),
            "options": {"expires": 600},
        },
        # every 15 min — run the per-meal food pass on meals missing a food record
        "backfill-meal-food": {
            "task": "tasks.backfill_meal_food_task",
            "schedule": crontab(minute="*/15"),
            "options": {"expires": 600},
        },
        # every 30 min — proactively rebuild recent day summaries left stale by
        # segment annotation, so yesterday's summary is ready before it's opened
        "rebuild-stale-day-summaries": {
            "task": "tasks.rebuild_stale_day_summaries_task",
            "schedule": crontab(minute="*/30"),
            "options": {"expires": 900},
        },
        # every 5 min — enforce 30-min TTL on non-whitelisted face embeddings
        "purge-face-embeddings": {
            "task": "tasks.purge_expired_face_embeddings_task",
            "schedule": crontab(minute="*/5"),
            "options": {"expires": 240},
        },
        # every 30 min — late-meal check per active device (device-local time)
        "check-meal-times": {
            "task": "tasks.check_meal_times_all_devices",
            "schedule": crontab(minute="*/30"),
            "options": {"expires": 1500},
        },
        # 04:00 UTC — refresh auto-learned usual meal times from last 30 days
        "relearn-meal-times": {
            "task": "tasks.relearn_meal_times_all_devices",
            "schedule": crontab(hour=4, minute=0),
        },
        # Monday 05:00 UTC — build the just-completed ISO week per device
        "weekly-summaries": {
            "task": "tasks.weekly_summaries_all_devices",
            "schedule": crontab(hour=5, minute=0, day_of_week=1),
        },
        # 05:30 UTC — refresh trip detection/summaries over the trailing window
        "detect-trips": {
            "task": "tasks.detect_trips_all_devices",
            "schedule": crontab(hour=5, minute=30),
        },
    },
    timezone="UTC",
)


# Patch Celery classes to support subscriptable type hints (e.g., AsyncResult[MyResultType])

classes = [
    Celery,
    Task,
    AbortableTask,
    AsyncResult,
    AbortableAsyncResult,
    FallbackContext,
    class_property,
]

for cls in classes:
    setattr(  # noqa: B010
        cls,
        "__class_getitem__",
        classmethod(lambda cls, *args, **kwargs: cls)
    )

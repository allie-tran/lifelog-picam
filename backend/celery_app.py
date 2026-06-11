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
    logging.getLogger("scripts").setLevel(logging.DEBUG)

celery = Celery(
    "picam-tasks",
    broker="redis://localhost:6379/0",
    backend="redis://localhost:6379/0",
    include=["tasks"],
)

from celery.signals import worker_ready

@worker_ready.connect
def _purge_stale_tasks(sender, **kwargs):
    """Discard tasks left in Redis from a previous worker run."""
    sender.app.control.purge()

celery.conf.update(
    worker_pool="solo",
    task_serializer="json",
    result_serializer="json",
    accept_content=["json"],
    task_track_started=True,
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
            "schedule": crontab(minute="*/30"),
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
        # every 5 min — enforce 30-min TTL on non-whitelisted face embeddings
        "purge-face-embeddings": {
            "task": "tasks.purge_expired_face_embeddings_task",
            "schedule": crontab(minute="*/5"),
            "options": {"expires": 240},
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

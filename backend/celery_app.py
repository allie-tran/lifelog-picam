from celery.app.task import Task
from celery.contrib.abortable import AbortableAsyncResult, AbortableTask
from celery.local import class_property
from celery.result import AsyncResult
from celery.utils.objects import FallbackContext
from celery import Celery
from dotenv import load_dotenv

load_dotenv()

celery = Celery(
    "picam-tasks",
    broker="redis://localhost:6379/0",
    backend="redis://localhost:6379/0",
    include=["tasks"],
)

# remove all pending tasks on startup
celery.control.purge()

celery.conf.update(
    worker_pool="solo",
    task_serializer="json",
    result_serializer="json",
    accept_content=["json"],
    task_track_started=True,
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

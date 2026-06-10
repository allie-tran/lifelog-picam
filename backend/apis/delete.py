import logging
import os
from datetime import datetime, timedelta, timezone
from typing import Annotated, List
from fastapi import Depends, FastAPI, HTTPException
from sqlalchemy import CursorResult, select, update
from sqlalchemy.orm import Session
from auth.auth_models import auth_dependency
from auth.types import AccessLevel
from constants import DIR
from database import get_session
from database.models import Image as ImageModel
from database.types import ImageRecord
from dependencies import CamelCaseModel
from auth import _require_owner
from pipelines.delete import remove_physical_images
from sessions.redis import redis_client

app = FastAPI()
logger = logging.getLogger(__name__)

_DELETED_IMAGES_LIMIT = 500
_PURGE_THRESHOLD_DAYS = 7

# ---------------------------------------------------------------------------
# Delete / restore endpoints
# ---------------------------------------------------------------------------
class DeleteImageRequest(CamelCaseModel):
    image_path: str
class DeleteImagesRequest(CamelCaseModel):
    image_paths: List[str]

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
    _require_owner(access_level)
    affected = session.execute(
        select(ImageModel.date, ImageModel.hour)
        .where(ImageModel.image_path == request.image_path)
        .where(ImageModel.device == device)
    ).fetchall()
    res = session.execute(
        update(ImageModel)
        .where(ImageModel.image_path == request.image_path)
        .where(ImageModel.device == device)
        .values(deleted=True, deleted_time=datetime.now(timezone.utc))
    )
    res = session.execute(stmt)
    logger.info(
        "Marked %d record(s) as deleted for image %s on device %s.",
        res.rowcount, request.image_path, device,  # type: ignore
    )
    session.commit()
    for date, hour in affected:
        if date and hour is not None:
            redis_client.delete_value(f"browse:{device}:{date}:{hour}")


@app.delete("/delete-images")
def delete_images(
    request: DeleteImagesRequest,
    device: str,
    access_level: Annotated[AccessLevel, Depends(auth_dependency)] = AccessLevel.NONE,
    session: Session = Depends(get_session),
):
    _require_owner(access_level)
    paths = [_resolve_image_path(device, p) for p in request.image_paths]
    affected = session.execute(
        select(ImageModel.date, ImageModel.hour)
        .where(ImageModel.image_path.in_(paths))
        .where(ImageModel.device == device)
        .distinct()
    ).fetchall()
    session.execute(
        update(ImageModel)
        .where(ImageModel.image_path.in_(paths))
        .where(ImageModel.device == device)
        .values(deleted=True, deleted_time=datetime.now(timezone.utc))
    )
    logger.info(
        "Marked %d record(s) as deleted for %d images on device %s.",
        len(paths), len(request.image_paths), device,  # type: ignore
    )
    session.commit()
    for date, hour in affected:
        if date and hour is not None:
            redis_client.delete_value(f"browse:{device}:{date}:{hour}")


@app.get("/get-deleted-images")
def get_deleted_images(
    device: str,
    access_level: Annotated[AccessLevel, Depends(auth_dependency)] = AccessLevel.NONE,
    session: Session = Depends(get_session),
):
    _require_owner(access_level)
    deleted_list = list(ImageRecord.find(
        session,
        deleted=True,
        device=device,
        sort="deleted_time",
        sort_desc=True,
        limit=_DELETED_IMAGES_LIMIT,
    ))
    logger.info("Found %d deleted images for device %s.", len(deleted_list), device)

    threshold = datetime.now(timezone.utc) - timedelta(days=_PURGE_THRESHOLD_DAYS)
    final_list = []
    to_purge = []

    for image in deleted_list:
        full_path = os.path.join(DIR, device, image.image_path)
        if not os.path.exists(full_path):
            to_purge.append(image.image_path)
        elif image.deleted_time and image.deleted_time < threshold:
            to_purge.append(image.image_path)
        else:
            final_list.append(image)

    if to_purge:
        logger.info("Auto-purging %d expired/missing images for device %s.", len(to_purge), device)
        remove_physical_images(session, device, to_purge)

    return final_list


@app.post("/restore-image")
def restore_image(
    request: DeleteImageRequest,
    device: str,
    access_level: Annotated[AccessLevel, Depends(auth_dependency)] = AccessLevel.NONE,
    session: Session = Depends(get_session),
):
    _require_owner(access_level)
    session.execute(
        update(ImageModel)
        .where(ImageModel.image_path == request.image_path)
        .where(ImageModel.device == device)
        .values(deleted=False, deleted_time=None)
    )
    session.commit()


@app.delete("/force-delete-image")
def force_delete_image(
    request: DeleteImageRequest,
    device: str,
    access_level: Annotated[AccessLevel, Depends(auth_dependency)] = AccessLevel.NONE,
    session: Session = Depends(get_session),
):
    _require_owner(access_level)
    remove_physical_images(session, device, [request.image_path])


@app.delete("/force-delete-images")
def force_delete_images(
    request: DeleteImagesRequest,
    device: str,
    access_level: Annotated[AccessLevel, Depends(auth_dependency)] = AccessLevel.NONE,
    session: Session = Depends(get_session),
):
    _require_owner(access_level)
    remove_physical_images(session, device, request.image_paths)

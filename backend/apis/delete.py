import os
from datetime import datetime, timedelta, timezone
from typing import Annotated, List
from fastapi import Depends, FastAPI, HTTPException
from sqlalchemy import update
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

app = FastAPI()

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
    stmt = (
        update(ImageModel)
        .where(ImageModel.image_path == request.image_path)
        .where(ImageModel.device == device)
        .values(deleted=True, deleted_time=datetime.now(timezone.utc))
    )
    print(stmt)
    res = session.execute(stmt)
    session.commit()
    print(
        f"Marked {res.rowcount} record(s) as deleted for image {request.image_path} on device {device}."
    )


@app.delete("/delete-images")
def delete_images(
    request: DeleteImagesRequest,
    device: str,
    access_level: Annotated[AccessLevel, Depends(auth_dependency)] = AccessLevel.NONE,
    session: Session = Depends(get_session),
):
    _require_owner(access_level)
    paths = [_resolve_image_path(device, p) for p in request.image_paths]
    session.execute(
        update(ImageModel)
        .where(ImageModel.image_path.in_(paths))
        .where(ImageModel.device == device)
        .values(deleted=True, deleted_time=datetime.now(timezone.utc))
    )
    session.commit()


@app.get("/get-deleted-images")
def get_deleted_images(
    device: str,
    access_level: Annotated[AccessLevel, Depends(auth_dependency)] = AccessLevel.NONE,
    session: Session = Depends(get_session),
):
    _require_owner(access_level)
    now = datetime.now(timezone.utc)
    deleted_list = ImageRecord.find(
        session,
        deleted=True,
        device=device,
        sort="deleted_time",
        sort_desc=True,
    )
    deleted_list = list(deleted_list)
    print(
        f"Took {(datetime.now(timezone.utc) - now).total_seconds():.2f} seconds to query deleted images."
    )
    print(f"Found {len(deleted_list)} deleted images for device {device}.")

    now_ms = datetime.now(timezone.utc)
    threshold = now_ms - timedelta(days=7)  # 7 days ago

    final_list = []

    to_delete = []
    for image in deleted_list:
        full_path = os.path.join(DIR, device, image.image_path)
        if not os.path.exists(full_path):
            to_delete.append(image.image_path)
        elif image.deleted_time and image.deleted_time < threshold:
            to_delete.append(image.image_path)
        else:
            final_list.append(image)
    if to_delete:
        remove_physical_images(session, device, to_delete)
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
    # remove_physical_image(device, image_path, collection, session)


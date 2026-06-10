
from typing import Annotated, List
import uuid
import numpy as np
from fastapi import Depends, FastAPI, HTTPException, UploadFile
from pydantic import BaseModel
from sqlalchemy import delete, insert, or_, select, update
from sqlalchemy.orm import Session

from app_types.general import LifelogImage
from auth import _require_any_access, _require_owner
from auth.auth_models import auth_dependency
from auth.types import AccessLevel
from database import get_session
from database.models import (
    Device,
    DeviceWhitelistEmbedding,
    DeviceWhitelistEntry,
    Image as ImageModel,
    ImagePerson,
    PeopleCluster,
)
from scripts.face_recognition import add_face_to_whitelist, search_for_faces
from tasks import relabel_whitelist_faces_task, setup_whitelist_clusters_task, setup_clustering_task
import logging

logger = logging.getLogger(__name__)

app = FastAPI()


@app.get("/health")
def health_check():
    return {"status": "ok"}


class WhitelistEntry(BaseModel):
    name: str
    images: List[str]


# ---------------------------------------------------------------------------
# Recognition mode endpoints
# ---------------------------------------------------------------------------


@app.get("/recognition-mode")
def get_recognition_mode(
    device: str,
    access_level: Annotated[AccessLevel, Depends(auth_dependency)] = AccessLevel.NONE,
    session: Session = Depends(get_session),
):
    _require_any_access(access_level)
    device_row = session.execute(select(Device).where(Device.device_id == device)).scalar()
    if not device_row:
        raise HTTPException(status_code=404, detail="Device not found")
    return {"keepFaceRecognition": device_row.keep_face_recognition}


@app.put("/set-recognition-mode")
async def set_recognition_mode(
    device: str,
    keep: bool,
    access_level: Annotated[AccessLevel, Depends(auth_dependency)] = AccessLevel.NONE,
    session: Session = Depends(get_session),
):
    logger.info(
        "Received request to set recognition mode for device %s to %s",
        device, keep
    )

    _require_owner(access_level)
    device_row = session.execute(select(Device).where(Device.device_id == device)).scalar()


    if not device_row:
        raise HTTPException(status_code=404, detail="Device not found")

    old_mode = device_row.keep_face_recognition
    if old_mode == keep:
        logger.info(
            "Recognition mode for device %s is already set to %s. No changes made.",
            device, keep
        )
        return {"keepFaceRecognition": keep, "changed": False}

    # Delete EVERY cluster that has any face from this device (device-scoped or legacy NULL-device),
    # plus whitelist-derived clusters tagged to this device.
    # ON DELETE CASCADE on ImagePerson.cluster_id NULLs all face assignments so the
    # background task starts from a clean slate.
    stmt = delete(PeopleCluster).where(PeopleCluster.device == device)
    result = session.execute(stmt)
    logger.info(
        "Deleted %d cluster(s) for device %s due to recognition mode change.",
        result.rowcount, device  # type: ignore
    )
    session.commit()

    session.execute(
        update(Device).where(Device.device_id == device).values(keep_face_recognition=keep)
    )
    session.commit()

    # Rebuild clusters in background
    try:
        if keep:
            setup_whitelist_clusters_task.apply_async(args=[device], retry=False)  # type: ignore
            logger.info("Triggered whitelist cluster setup for device %s.", device)
        else:
            setup_clustering_task.apply_async(args=[device], retry=False)  # type: ignore
            logger.info("Triggered full clustering for device %s.", device)
    except Exception as e:
        logger.warning("Celery dispatch failed for device %s: %s", device, e)

    return {"keepFaceRecognition": keep, "changed": True}


@app.get("/all-device-settings")
def get_all_device_settings(
    access_level: Annotated[AccessLevel, Depends(auth_dependency)] = AccessLevel.NONE,
    session: Session = Depends(get_session),
):
    """Admin-only: returns recognition mode flag for every device."""
    _require_owner(access_level)
    devices = session.execute(select(Device)).scalars().all()
    return [{"deviceId": d.device_id, "keepFaceRecognition": d.keep_face_recognition} for d in devices]


# ---------------------------------------------------------------------------
# Face search
# ---------------------------------------------------------------------------


@app.post("/get-faces", response_model=List[LifelogImage])
def get_faces_from_files(
    files: List[UploadFile],
    device: str,
    access_level: Annotated[AccessLevel, Depends(auth_dependency)] = AccessLevel.NONE,
    session: Session = Depends(get_session),
):
    _require_any_access(access_level)
    images = search_for_faces(session, device, files)
    return images


# ---------------------------------------------------------------------------
# Whitelist management
# ---------------------------------------------------------------------------


@app.put("/add-to-whitelist")
def add_to_whitelist(
    files: List[UploadFile],
    device: str,
    name: str,
    access_level: Annotated[AccessLevel, Depends(auth_dependency)] = AccessLevel.NONE,
    session: Session = Depends(get_session),
):
    _require_owner(access_level)
    new_embeddings = add_face_to_whitelist(session, device, name, files)
    if new_embeddings:
        relabel_whitelist_faces_task.delay(device, name, new_embeddings)

    # Keep the cluster centroid in sync if device is in whitelist mode
    device_row = session.execute(select(Device).where(Device.device_id == device)).scalar()
    if device_row and device_row.keep_face_recognition:
        _sync_cluster_for_entry(session, device, device_row, name)
        session.commit()

    return {"message": "Added to whitelist. Existing thumbnails will be updated in the background."}


@app.get("/get-whitelist", response_model=List[WhitelistEntry])
def get_whitelist(
    device: str,
    access_level: Annotated[AccessLevel, Depends(auth_dependency)] = AccessLevel.NONE,
    session: Session = Depends(get_session),
):
    _require_owner(access_level)
    ids = session.execute(select(Device.id).where(Device.device_id == device)).fetchone()
    if not ids:
        raise HTTPException(status_code=404, detail="Device not found")

    entrys = (
        session.execute(
            select(DeviceWhitelistEntry).where(DeviceWhitelistEntry.device_id == ids[0])
        )
        .scalars()
        .all()
    )

    return [
        {
            "name": e.name,
            "images": [f"data:image/jpeg;base64, {img}" for img in e.cropped[:2]],
        }
        for e in entrys
    ]


@app.get("/images-by-name")
def get_images_by_name(
    device: str,
    name: str,
    access_level: Annotated[AccessLevel, Depends(auth_dependency)] = AccessLevel.NONE,
    session: Session = Depends(get_session),
):
    _require_owner(access_level)
    rows = session.execute(
        select(ImageModel.image_path, ImageModel.thumbnail, ImageModel.timestamp)
        .join(ImagePerson, ImagePerson.image_id == ImageModel.id)
        .join(PeopleCluster, PeopleCluster.id == ImagePerson.cluster_id)
        .where(
            PeopleCluster.cluster_label == name,
            ImageModel.device == device,
            ImageModel.deleted == False,
        )
        .order_by(ImageModel.timestamp.desc())
        .limit(100)
    ).all()

    return [
        {
            "imagePath": row.image_path,
            "thumbnail": row.thumbnail,
            "timestamp": row.timestamp.isoformat() if row.timestamp else None,
        }
        for row in rows
    ]


@app.post("/relabel-recent")
def relabel_recent(
    device: str,
    hours: int = 24,
    access_level: Annotated[AccessLevel, Depends(auth_dependency)] = AccessLevel.NONE,
    session: Session = Depends(get_session),
):
    """Trigger relabeling of redacted faces in the last N hours for all whitelist entries."""
    _require_owner(access_level)

    device_id = session.execute(select(Device.id).where(Device.device_id == device)).scalar()
    if not device_id:
        raise HTTPException(status_code=404, detail="Device not found")

    entries = session.execute(
        select(DeviceWhitelistEntry).where(DeviceWhitelistEntry.device_id == device_id)
    ).scalars().all()

    queued = 0
    for entry in entries:
        emb_rows = session.execute(
            select(DeviceWhitelistEmbedding.embedding).where(DeviceWhitelistEmbedding.entry_id == entry.id)
        ).scalars().all()
        if not emb_rows:
            continue
        embeddings = [list(map(float, e)) for e in emb_rows]
        relabel_whitelist_faces_task.apply_async(
            args=(device, str(entry.name), embeddings),
            kwargs={"since_hours": hours},
        )
        queued += 1

    return {"queued": queued, "hours": hours}


@app.delete("/remove-from-whitelist")
def remove_from_whitelist(
    device: str,
    name: str,
    access_level: Annotated[AccessLevel, Depends(auth_dependency)] = AccessLevel.NONE,
    session: Session = Depends(get_session),
):
    _require_owner(access_level)
    device_id = session.execute(select(Device.id).where(Device.device_id == device)).scalar()
    if not device_id:
        raise HTTPException(status_code=404, detail="Device not found")

    # PeopleCluster.whitelist_entry_id has ON DELETE CASCADE, so deleting the entry
    # automatically removes the corresponding cluster and NULLs ImagePerson.cluster_id.
    session.execute(
        delete(DeviceWhitelistEntry)
        .where(DeviceWhitelistEntry.device_id == device_id)
        .where(DeviceWhitelistEntry.name == name)
    )
    session.commit()


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _sync_cluster_for_entry(session: Session, device: str, device_row: Device, name: str) -> None:
    """Create or update the PeopleCluster that mirrors a whitelist entry."""
    entry = session.execute(
        select(DeviceWhitelistEntry).where(
            DeviceWhitelistEntry.device_id == device_row.id,
            DeviceWhitelistEntry.name == name,
        )
    ).scalar()
    if not entry:
        return

    emb_rows = session.execute(
        select(DeviceWhitelistEmbedding.embedding).where(DeviceWhitelistEmbedding.entry_id == entry.id)
    ).scalars().all()
    if not emb_rows:
        return

    emb_matrix = np.array([np.array(e, dtype=np.float32) for e in emb_rows])
    center = emb_matrix.mean(axis=0)
    norm = np.linalg.norm(center)
    if norm > 1e-8:
        center /= norm

    existing = session.execute(
        select(PeopleCluster).where(PeopleCluster.whitelist_entry_id == entry.id)
    ).scalar()
    if existing:
        existing.center_embedding = center.tolist()
    else:
        session.add(PeopleCluster(
            id=uuid.uuid4(),
            cluster_label=name,
            center_embedding=center.tolist(),
            device=device,
            whitelist_entry_id=entry.id,
        ))



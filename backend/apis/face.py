
from typing import Annotated, List
from fastapi import Depends, FastAPI, HTTPException, UploadFile
from pydantic import BaseModel
from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app_types.general import LifelogImage
from auth import _require_any_access, _require_owner
from auth.auth_models import auth_dependency
from auth.types import AccessLevel
from database import get_session
from database.models import Device, DeviceWhitelistEntry
from scripts.face_recognition import add_face_to_whitelist, search_for_faces


app = FastAPI()
@app.get("/health")
def health_check():
    return {"status": "ok"}


class WhitelistEntry(BaseModel):
    name: str
    images: List[str]

# ---------------------------------------------------------------------------
# Face endpoints
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


@app.put("/add-to-whitelist")
def add_to_whitelist(
    files: List[UploadFile],
    device: str,
    name: str,
    access_level: Annotated[AccessLevel, Depends(auth_dependency)] = AccessLevel.NONE,
    session: Session = Depends(get_session),
):
    _require_owner(access_level)
    add_face_to_whitelist(session, device, name, files)


@app.get("/get-whitelist", response_model=List[WhitelistEntry])
def get_whitelist(
    device: str,
    access_level: Annotated[AccessLevel, Depends(auth_dependency)] = AccessLevel.NONE,
    session: Session = Depends(get_session),
):
    _require_owner(access_level)
    ids = session.execute(
        select(Device.id).where(Device.device_id == device)
    ).fetchone()

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


@app.delete("/remove-from-whitelist")
def remove_from_whitelist(
    device: str,
    name: str,
    access_level: Annotated[AccessLevel, Depends(auth_dependency)] = AccessLevel.NONE,
    session: Session = Depends(get_session),
):
    _require_owner(access_level)
    device_id = session.execute(
        select(Device.id).where(Device.device_id == device)
    ).scalar()

    if not device_id:
        raise HTTPException(status_code=404, detail="Device not found")

    session.execute(
        delete(DeviceWhitelistEntry)
        .where(DeviceWhitelistEntry.device_id == device_id)
        .where(DeviceWhitelistEntry.name == name)
    )
    session.commit()

from datetime import datetime
from typing import List
from fastapi import UploadFile
from sqlalchemy import insert, select
from app_types import LifelogImage
from constants import EMBEDDING_DIR
from database.models import DeviceWhitelistEmbedding, DeviceWhitelistEntry, Image, ImagePerson, Device
from database.types import _orm_to_lifelog
import cv2
import numpy as np

from scripts.object_detection import get_face_data_from_person_crop
from scripts.utils import to_base64


directory = EMBEDDING_DIR


def delete_old_faces(session, device, cutoff_timestamp: datetime):
    stmt = (
        select(ImagePerson.id)
        .where(Image.device == device, Image.timestamp < cutoff_timestamp)
        .join(Image, Image.id == ImagePerson.image_id)
        .where(Image.deleted == False)
    )
    id_list = [row.id for row in session.execute(stmt).fetchall()]
    if id_list:
        print(f"TEST: Would delete {len(id_list)} old face embeddings for device {device}.")
        print("This does nothing for now.")
        # TODO
        # res = session.execute(delete(ImagePerson).where(ImagePerson.id.in_(id_list)))
        # session.commit()
        # print(f"Deleted {res.rowcount} old face embeddings for device {device}.")

def search_face_embedding(session, device: str, emb: list[float], top_k: int = 5):
    rows = session.execute(
        select(
            ImagePerson.image_id,
            Image,
            ImagePerson.label,
            ImagePerson.confidence,
            ImagePerson.embedding.cosine_distance(emb).label("face_distance"),
        )
        .join(Image, Image.id == ImagePerson.image_id)
        .where(Image.deleted == False)
        .where(Image.device == device)
        .where(ImagePerson.embedding.isnot(None))
        .order_by(ImagePerson.embedding.cosine_distance(emb))
        .limit(top_k)
    ).fetchall()
    return [_orm_to_lifelog(row.Image) for row in rows]  # type: ignore


def search_for_faces(
    session, device: str, files: List[UploadFile]
) -> list[LifelogImage]:
    results = []
    for file in files:
        cv_image = cv2.imdecode(
            np.frombuffer(file.file.read(), np.uint8), cv2.IMREAD_COLOR
        )
        faces = get_face_data_from_person_crop(cv_image)
        print(f"Detected {len(faces)} faces in the uploaded image.")
        if not faces:
            continue
        face = faces[0].embedding
        results += search_face_embedding(session, device, face, top_k=5)
    return results


def add_face_to_whitelist(session, device: str, name: str, files: List[UploadFile]):
    cropped = []
    embeddings = []

    for file in files:
        cv_image = cv2.imdecode(
            np.frombuffer(file.file.read(), np.uint8), cv2.IMREAD_COLOR
        )
        if cv_image is None:
            print("Error: Unable to read the uploaded image.")
            continue
        faces = get_face_data_from_person_crop(cv_image)
        if not faces:
            continue
        face = faces[0].embedding
        bbox = faces[0].bbox
        # expand the box by 20% in each direction
        x1, y1, x2, y2 = bbox
        w = x2 - x1
        h = y2 - y1
        x1 = max(0, x1 - int(w * 0.2))
        y1 = max(0, y1 - int(h * 0.2))
        x2 = min(cv_image.shape[1], x2 + int(w * 0.2))
        y2 = min(cv_image.shape[0], y2 + int(h * 0.2))
        cropped_image = cv_image[y1:y2, x1:x2]
        image_bytes = cv2.imencode(".jpg", cropped_image)[1].tobytes()

        embeddings.append(face)
        cropped.append(to_base64(image_bytes))

    # Update the whitelist entry first
    res = session.execute(
        insert(DeviceWhitelistEntry)
        .values(
            device_id=session.execute(select(Device.id).where(Device.device_id == device)).scalar_one(),
            name=name,
            cropped=cropped,
        )
    )
    session.commit()
    entry_id = res.inserted_primary_key[0]
    for embedding in embeddings:
        session.execute(
            insert(DeviceWhitelistEmbedding).values(
                entry_id=entry_id,
                embedding=embedding,
            )
        )

import os

from sqlalchemy import delete, insert, select, text, update
from constants import DIR, THUMBNAIL_DIR
from database.models import Image, ImageEmbedding
from database.types import ImageRecord
from database.vector_database import delete_embedding
import zvec
from datetime import datetime, timezone


def remove_physical_images(session, device_id: str, image_paths: list[str]):
    """Removes multiple images for a device, including physical files, MongoDB records, thumbnails, and ZVec embeddings."""
    # Physical files
    for image_path in image_paths:
        full_path = os.path.join(DIR, device_id, image_path)
        if os.path.exists(full_path):
            os.remove(full_path)
        thumbnail_path = os.path.join(
            THUMBNAIL_DIR, device_id, image_path.replace(".jpg", ".webp")
        )
        if os.path.exists(thumbnail_path):
            os.remove(thumbnail_path)

    # Database
    # Get id first for image paths to delete corresponding embeddings
    ids = session.execute(
        text(
            f"SELECT id FROM images WHERE device = :device_id AND image_path IN :paths"
        ),
        {"device_id": device_id, "paths": tuple(image_paths)},
    ).fetchall()

    stmt = delete(Image).where(Image.id.in_(ids))
    count = session.execute(stmt).rowcount
    print(f"Deleted {count} records from MongoDB for device {device_id}.")

    # Vector
    stmt = delete(ImageEmbedding).where(ImageEmbedding.image_id.in_(ids))
    count = session.execute(stmt).rowcount
    print(f"Deleted {count} embeddings from MongoDB for device {device_id}.")


def remove_physical_image(
    device_id: str, image_path: str, collection: zvec.Collection, session
):
    """Full cleanup"""
    # Physical file
    full_path = os.path.join(DIR, device_id, image_path)
    if os.path.exists(full_path):
        os.remove(full_path)

    # Thumbnail
    thumbnail_path = os.path.join(
        THUMBNAIL_DIR, device_id, image_path.replace(".jpg", ".webp")
    )
    if os.path.exists(thumbnail_path):
        os.remove(thumbnail_path)

    # Database
    stmt = delete(Image).where(
        Image.device == device_id, Image.image_path == image_path
    )
    count = session.execute(stmt).rowcount
    print(f"Deleted {count} records from MongoDB for device {device_id} and image {image_path}.")

    # Vector
    image_id = session.execute(
        select(Image.id).where(
            Image.device == device_id, Image.image_path == image_path
        )
    ).scalar_one_or_none()
    if image_id:
        delete_embedding(collection, image_id)
        stmt = delete(ImageEmbedding).where(ImageEmbedding.image_id == image_id)
        count = session.execute(stmt).rowcount
        print(f"Deleted {count} embeddings from MongoDB for device {device_id} and image {image_path}.")



def mark_error(
    session, device_id: str, date: str, image_path: str, timestamp: float
):
    """
    This function adds a MongoDB placeholder entry just to tell the device to not keep sending the same image over and over again. It doesn't do any cleanup.
    """
    print(
        f"Marking {image_path} for device {device_id} as deleted to prevent reprocessing."
    )
    # check if already exists
    existing = session.execute(
        select(Image).where(Image.device == device_id, Image.image_path == image_path)
    ).fetchone()
    if existing:
        session.execute(update(Image).where(Image.device == device_id, Image.image_path == image_path).values(deleted=True))
    else:
        session.execute(
            insert(Image).values(
                device=device_id,
                image_path=image_path,
                deleted=True,
                deleted_time=datetime.now(timezone.utc),
                timestamp=timestamp,
                isVideo=False,
                date=date,
            )
        )

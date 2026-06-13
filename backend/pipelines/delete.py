import os

from sqlalchemy import delete, select, update, insert
from core.config import DIR, THUMBNAIL_DIR, BACKUP_DIR
from database.models import Image
from datetime import datetime, timezone


def temp_backup(path):
    filename = path.replace(DIR, BACKUP_DIR)
    os.makedirs(os.path.dirname(filename), exist_ok=True)
    os.rename(path, filename)

def remove_physical_images(session, device_id: str, image_paths: list[str]):
    """Removes multiple images for a device, including physical files, MongoDB records, thumbnails, and ZVec embeddings."""
    # Physical files
    for image_path in image_paths:
        full_path = os.path.join(DIR, device_id, image_path)
        if os.path.exists(full_path):
            # os.remove(full_path)
            temp_backup(full_path)

        thumbnail_path = os.path.join(
            THUMBNAIL_DIR, device_id, image_path.replace(".jpg", ".webp")
        )
        if os.path.exists(thumbnail_path):
            os.remove(thumbnail_path)

    # Database
    stmt = delete(Image).where(Image.device == device_id, Image.image_path.in_(image_paths))
    count = session.execute(stmt).rowcount
    print(f"Deleted {count} records from MongoDB for device {device_id}.")
    session.commit()


def mark_error( session, device_id: str, date: str, image_path: str, timestamp: datetime
):
    """
    This function adds a MongoDB placeholder entry just to tell the device to not keep sending the same image over and over again. It doesn't do any cleanup.
    """
    # check if already exists
    existing = session.execute(
        select(Image).where(Image.device == device_id, Image.image_path == image_path)
    ).fetchone()
    if existing:
        session.execute(update(Image).where(Image.device == device_id, Image.image_path == image_path).values(deleted=True))
    else:
        stmt = insert(Image).values(
            device=device_id,
            image_path=image_path,
            deleted=True,
            deleted_time=datetime.now(timezone.utc),
            thumbnail=image_path.replace(".jpg", ".webp"),
            timestamp=timestamp,
            is_video=False,
            date=date,
        )
        session.execute(stmt)

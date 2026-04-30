import glob
import json
import os
import random
import secrets
from datetime import datetime

import cv2
import numpy as np
import piexif
from dotenv import load_dotenv
from PIL import Image as PILImage
from pymongo import MongoClient
from scipy.stats import ortho_group
from sqlalchemy import Float, cast, create_engine, delete, or_, select, update
from sqlalchemy.orm import Session, selectinload
from tqdm import tqdm

# Import your models from models.py
from models import Image, ImageObject, ImagePerson

load_dotenv()

seed = 42
random.seed(seed)
np.random.seed(seed)

# --- Configuration ---
PG_URI = os.getenv("PG_URI")  # Your PostgreSQL connection string
SRC_DIR = os.getenv("DIR", "data/images")  # Where original images are stored
THUMB_DIR = os.getenv("THUMBNAIL_DIR", "data/thumbnails")  # Where thumbnails are stored
OUT_DIR = os.getenv(
    "OUT_DIR", "data/published"
)  # Where to save published images and metadata

assert PG_URI, "PostgreSQL URI must be set in .env"
engine = create_engine(PG_URI)
mongo_client = MongoClient("mongodb://localhost:27018/")
collection = mongo_client["picam"]["images"]


def cap_bbox(bbox, img_width, img_height):
    x_min, y_min, x_max, y_max = bbox
    return [
        max(0, min(x_min, img_width)),
        max(0, min(y_min, img_height)),
        max(0, min(x_max, img_width)),
        max(0, min(y_max, img_height)),
    ]


def relative_bbox(bbox, img_width, img_height):
    x_min, y_min, x_max, y_max = bbox
    # check if all values are already between 0 and 1
    if all(0 <= val <= 1 for val in [x_min, y_min, x_max, y_max]):
        return bbox

    return [
        round(x_min / img_width, 4),
        round(y_min / img_height, 4),
        round(x_max / img_width, 4),
        round(y_max / img_height, 4),
    ]


def absolute_bbox(bbox, img_width, img_height):
    x_min, y_min, x_max, y_max = bbox

    # check if all values are already absolute (greater than 1)
    if all(val > 1 for val in [x_min, y_min, x_max, y_max]):
        return bbox

    return [
        round(x_min * img_width),
        round(y_min * img_height),
        round(x_max * img_width),
        round(y_max * img_height),
    ]


BATCH_SIZE = 10000


def update_bounding_boxes(device, date):
    with Session(engine) as session:
        stmt = (
            select(Image)
            .outerjoin(Image.people)
            .outerjoin(Image.objects)
            .options(selectinload(Image.people), selectinload(Image.objects))
            .where(
                Image.device == device,
                Image.date == date,
                or_(ImagePerson.rel_bbox.is_(None), ImageObject.rel_bbox.is_(None)),
            )
            .distinct()
        )

        images = session.execute(stmt).scalars().all()

        people_rows = []
        object_rows = []

        images = [img for img in images if (img.people and any(p.rel_bbox is None for p in img.people)) or (img.objects and any(o.rel_bbox is None for o in img.objects))]
        if not images:
            print(f"No images with missing bounding boxes for {device} {date}")
            return

        for img in tqdm(images, desc=f"Updating bounding boxes for {device} {date}"):
            img_path = os.path.join(SRC_DIR, img.device, img.image_path)
            h, w = cv2.imread(img_path).shape[:2]

            if img.objects:
                for obj in img.objects:
                    if obj.bbox is None:
                        continue
                    original_bbox = obj.bbox
                    rel_bbox = relative_bbox(original_bbox, w, h)
                    rel_bbox = cap_bbox(rel_bbox, 1.0, 1.0)
                    object_rows.append(
                        {
                            "id": obj.id,
                            "rel_bbox": rel_bbox,
                        }
                    )

            if img.people:
                for person in img.people:
                    if person.rel_bbox:
                        continue
                    original_bbox = person.bbox
                    rel_bbox = relative_bbox(original_bbox, w, h)
                    rel_bbox = cap_bbox(rel_bbox, 1.0, 1.0)
                    people_rows.append(
                        {
                            "id": person.id,
                            "rel_bbox": rel_bbox,
                        }
                    )

            if len(people_rows) >= BATCH_SIZE:
                session.bulk_update_mappings(ImagePerson, people_rows)
                people_rows = []
                session.commit()

            if len(object_rows) >= BATCH_SIZE:
                session.bulk_update_mappings(ImageObject, object_rows)
                object_rows = []
                session.commit()

        if people_rows:
            session.bulk_update_mappings(ImagePerson, people_rows)

        if object_rows:
            session.bulk_update_mappings(ImageObject, object_rows)

        session.commit()


if __name__ == "__main__":
    for device in ["allie", "cathal"]:
        dates = os.listdir(os.path.join(SRC_DIR, device))
        dates = sorted(dates)
        for date in dates:
            update_bounding_boxes(device, date)

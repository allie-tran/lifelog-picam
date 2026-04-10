import json
import os
import random
import secrets
from datetime import datetime

import numpy as np
import piexif
from dotenv import load_dotenv
from PIL import Image as PILImage
from scipy.stats import ortho_group
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session, selectinload
from tqdm import tqdm
import glob

# Import your models from models.py
from models import Image

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


# ------------------------------------------
# FACE EMBEDDING TRANSFORMATION
# -------------------------------------------
def generate_secure_transformation_matrix(dimension):
    """
    Generates a cryptographically secure orthonormal matrix.
    Uses 'secrets' to generate a seed for the orthogonal group generation.
    """
    # Generate a high-entropy 32-bit integer seed
    # We use 32-bit because most underlying PRNG seeds for ortho_group
    # expect a standard integer range.
    secure_seed = secrets.randbits(32)

    # Generate the matrix using the Haar distribution
    # We provide the secure seed to the Generator
    rng = np.random.default_rng(secure_seed)
    matrix = ortho_group.rvs(dim=dimension, random_state=rng)

    return matrix


def apply_transformation(embedding, transform_matrix):
    """
    Applies the transformation M to a face embedding vector.

    Args:
        embedding: A 1D numpy array (the face embedding)
        transform_matrix: The orthonormal matrix M
    Returns:
        The transformed (rotated) embedding
    """
    if transform_matrix is None:
        return embedding
    # Ensure the embedding is treated as a column vector for the dot product
    return np.dot(transform_matrix, embedding)


matrix = generate_secure_transformation_matrix(512)
# -------------------------------------------
# METADATA SERIALIZATION
# -------------------------------------------


def encode_embedding(embedding, transform_matrix=None):
    if embedding is None:
        return None

    if transform_matrix is not None:
        embedding = apply_transformation(embedding, transform_matrix)
    return embedding.tolist()


def get_full_metadata(image_row: Image) -> dict:
    """Serializes relational data into a dictionary for JSON."""
    return {
        "time": {
            "timestamp": image_row.timestamp.isoformat(),
            "local_timestamp": image_row.local_timestamp.isoformat(),
            "timezone": image_row.timezone,
        },
        "location": {
            "vaisl": {
                "fsq_id": image_row.location.fsq_id,
                "name": image_row.location.name,
                "info": image_row.location.info,
                "address": image_row.location.address,
                "country": image_row.location.country,
                "stop": image_row.location.stop,
            },
            "gps": (
                {
                    "latitude": image_row.gps.latitude,
                    "longitude": image_row.gps.longitude,
                    "elevation": image_row.gps.elevation,
                    "interpolated": image_row.gps.interpolated,
                }
                if image_row.gps
                else None
            ),
        },
        "detections": {
            "objects": [
                {"label": o.label, "conf": o.confidence, "bbox": o.bbox}
                for o in image_row.objects
            ],
            "faces": [
                {
                    "name": p.label,
                    "conf": p.confidence,
                    "bbox": p.bbox,
                    "embedding": encode_embedding(p.embedding, matrix),
                }
                for p in image_row.people
            ],
            # "ocr": [
            #     {"text": t.text, "conf": t.confidence, "bbox": t.box_2d}
            #     for t in image_row.ocr
            # ],
        },
        "clip_embedding": (
            encode_embedding(image_row.clip_embedding.embedding)
            if image_row.clip_embedding
            else None
        ),
    }

def copy_old_lsc_thumbnails():
    OLD = "/mnt/ssd0/Images/LSC23/"
    for month in os.listdir(OLD):
        if month.startswith("2019") or month.startswith("2020"):
            all_files = glob.glob(os.path.join(OLD, month, "**/*.jpg"), recursive=True)
            for file in tqdm(all_files, desc=f"Processing {month}"):
                date = datetime.strptime(os.path.basename(file), "%Y%m%d_%H%M%S_000.jpg")
                date_str = date.strftime("%Y-%m-%d")
                new_basename = date.strftime("%Y%m%d_%H%M%S.webp")
                # copy
                target_dir = os.path.join(THUMB_DIR, "cathal", date_str)
                os.makedirs(target_dir, exist_ok=True)
                img = PILImage.open(file)
                img.save(os.path.join(target_dir, new_basename), "WEBP", quality=100)

def publish_batch(limit=50):
    with Session(engine) as session:
        stmt = (
            select(Image)
            .options(
                selectinload(Image.gps),
                selectinload(Image.objects),
                selectinload(Image.people),
                selectinload(Image.clip_embedding),
                selectinload(Image.location),
                selectinload(Image.annotations),
            )
            .where(Image.device == "cathal", Image.year == 2022)
            .order_by(Image.local_timestamp)
            .limit(limit)
        )

        results = session.scalars(stmt).all()
        metadata = {}

        for img in results:

            # 1. Path Setup
            # Adjusting path logic to match your device-based subfolders
            src_path = f"{SRC_DIR}/{img.device}/{img.image_path}"
            thumb_source = f"{THUMB_DIR}/{img.device}/{img.image_path}"

            # Destination: data/published/YYYY/MM/DD/filename.jpg
            dt = img.local_timestamp or datetime.now()
            target_dir = os.path.join(
                OUT_DIR, f"{dt.year}", f"{dt.month:02d}", f"{dt.day:02d}"
            )
            os.makedirs(target_dir, exist_ok=True)
            base_name = os.path.basename(str(img.image_path))
            target_img = os.path.join(target_dir, base_name)

            try:
                # 2. Handle Image & EXIF
                # We load EXIF from the ORIGINAL (src_path) but save it to the THUMBNAIL
                if os.path.exists(src_path) and os.path.exists(thumb_source):
                    exif_dict = piexif.load(src_path)

                    # Optional: Inject your DB data into the EXIF object here
                    # (See previous logic for piexif.ImageIFD.XPKeywords etc.)
                    exif_bytes = piexif.dump(exif_dict)
                    with PILImage.open(thumb_source) as t_img:
                        t_img.save(target_img, "JPEG", exif=exif_bytes, quality=95)

                # 3. Generate Metadata JSON
                relative_img_path = os.path.relpath(target_img, OUT_DIR)
                img_metadata = get_full_metadata(img)
                img_metadata["image_path"] = relative_img_path
                metadata[relative_img_path] = img_metadata

            except Exception as e:
                print(f"Failed {img.id}: {e}")

    with open(os.path.join(OUT_DIR, "metadata.json"), "w") as f:
        json.dump(metadata, f, indent=4)

if __name__ == "__main__":
    copy_old_lsc_thumbnails()
    publish_batch()

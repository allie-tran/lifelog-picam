import json
import glob
import os
import random
import secrets
from datetime import datetime

import numpy as np
from dotenv import load_dotenv
from scipy.stats import ortho_group
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session, selectinload
from concurrent.futures import ProcessPoolExecutor
from tqdm import tqdm

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
CLIP_EMBEDDING_DIR = "/mnt/ssd0/embeddings/cathal/vitl14336/"


def get_clip_embedding(image_row):
    basename = os.path.basename(image_row.image_path)
    clip_path = os.path.join(CLIP_EMBEDDING_DIR, f"{basename}.npy")
    if os.path.exists(clip_path):
        return np.load(clip_path)
    print(f"CLIP embedding not found for {image_row.image_path} at {clip_path}")
    return None


def encode_embedding(embedding, transform_matrix=None):
    if embedding is None:
        return None

    if transform_matrix is not None:
        embedding = apply_transformation(embedding, transform_matrix)
    return embedding.tolist()


def get_full_metadata(image_row: Image) -> dict:
    """Serializes relational data into a dictionary for JSON."""
    return {
        "image": {
            "original_width": image_row.width,
            "original_height": image_row.height,
        },
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
                {
                    "label": o.label,
                    "conf": o.confidence,
                    "bbox": o.bbox,
                    "rel_bbox": o.rel_bbox,
                }
                for o in image_row.objects
            ],
            "faces": [
                {
                    "name": p.label,
                    "conf": p.confidence,
                    "bbox": p.bbox,
                    "embedding": encode_embedding(p.embedding, matrix),
                    "rel_bbox": p.rel_bbox,
                }
                for p in image_row.people
            ],
            # "ocr": [
            #     {"text": t.text, "conf": t.confidence, "bbox": t.box_2d}
            #     for t in image_row.ocr
            # ],
        },
        "clip_embedding": encode_embedding(get_clip_embedding(image_row)),
    }


def copy_old_lsc_thumbnails():
    OLD = "/mnt/ssd0/Images/LSC23/"
    months = sorted(os.listdir(OLD))
    for month in months:
        if month.startswith("2019") or month.startswith("2020"):
            all_files = glob.glob(os.path.join(OLD, month, "**/*.jpg"), recursive=True)
            all_files = sorted(all_files)
            for file in tqdm(all_files, desc=f"Processing {month}"):
                # date = datetime.strptime(os.path.basename(file), "%Y%m%d_%H%M%S_000.jpg")
                # date_str = date.strftime("%Y-%m-%d")
                new_basename = os.path.basename(file).replace("_000.jpg", ".webp")
                date_str = new_basename.split("_")[0]
                date_str = f"{date_str[:4]}-{date_str[4:6]}-{date_str[6:8]}"
                # copy
                target_dir = os.path.join(THUMB_DIR, "cathal", date_str)
                os.makedirs(target_dir, exist_ok=True)
                os.system(f"cp {file} {os.path.join(target_dir, new_basename)}")
                # img = PILImage.open(file)
                # img.save(os.path.join(target_dir, new_basename), "WEBP", quality=100)


def publish_batch(start, end):
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
            .where(Image.device == "cathal")
            .where(Image.deleted == False)
            .where(Image.timestamp >= start, Image.timestamp < end)
            .order_by(Image.timestamp)
        )

        results = session.execute(stmt).scalars()
        metadata = {}

        for img in tqdm(results, desc=f"Publishing {start.date()} to {end.date()}"):
            # 1. Path Setup
            # Adjusting path logic to match your device-based subfolders
            src_path = f"{SRC_DIR}/{img.device}/{img.image_path}"
            thumb_source = f"{THUMB_DIR}/{img.device}/{img.thumbnail}"

            # Destination: data/published/YYYY/MM/DD/filename.jpg
            dt = img.timestamp or datetime.now()
            target_dir = os.path.join(
                OUT_DIR, f"{dt.year}", f"{dt.month:02d}", f"{dt.day:02d}"
            )
            os.makedirs(target_dir, exist_ok=True)
            base_name = os.path.basename(str(img.image_path))
            target_img = os.path.join(target_dir, base_name.replace(".jpg", ".webp"))

            try:
                # 1. Copy Thumbnail to Published Folder
                if os.path.exists(src_path) and os.path.exists(thumb_source):
                    if not os.path.exists(target_img):
                        copy_cmd = f"cp {thumb_source} {target_img}"
                        os.system(copy_cmd)

                    # 2. Generate Metadata JSON
                    relative_img_path = os.path.relpath(target_img, OUT_DIR)
                    img_metadata = get_full_metadata(img)
                    img_metadata["image"]["path"] = relative_img_path
                    metadata[relative_img_path] = img_metadata
                else:
                    if os.path.exists(src_path):
                        print(f"Thumbnail missing for {img.id} at {thumb_source}")
                    if not os.path.exists(src_path):
                        print(f"Source image missing for {img.id} at {src_path}")
                    continue

            except Exception as e:
                print(f"Failed {img.id}: {e}")

    return metadata


import pyzipper  # Better encryption support than standard zipfile
from huggingface_hub import HfApi

# --- New Configuration for HF ---
HF_REPO_ID = "allietran/LSC26"
HF_TOKEN = os.getenv("HF_TOKEN")  # Add this to your .env
assert HF_TOKEN, "Hugging Face token must be set in .env"
ZIP_PASSWORD = os.getenv("ZIP_PASSWORD", "secure_default_pass")


def zip_monthly_data(args):
    year, month, password = args

    """Zips a specific month's folder with AES encryption."""
    month_str = f"{month:02d}"
    folder_to_zip = os.path.join(OUT_DIR, str(year), month_str)
    output_zip = os.path.join(OUT_DIR, f"{year}/{year}-{month_str}.zip")

    if not os.path.exists(folder_to_zip):
        print(f"Folder {folder_to_zip} not found. Skipping zip.")
        return None

    if os.path.exists(output_zip):
        print(f"Zip {output_zip} already exists. Skipping.")
        return output_zip

    files_to_add = []
    for root, _, filenames in os.walk(folder_to_zip):
        for f in filenames:
            full_path = os.path.join(root, f)
            arcname = os.path.relpath(full_path, OUT_DIR)  # Store relative path in zip
            files_to_add.append((full_path, arcname))

    compression = pyzipper.ZIP_DEFLATED
    with pyzipper.AESZipFile(
        output_zip,
        "w",
        compression=compression,
        compresslevel=1,  # 1 = fast, 9 = small
        encryption=pyzipper.WZ_AES,
    ) as zf:
        zf.setpassword(password.encode())
        for full_path, arcname in tqdm(
            files_to_add, desc=f"Zipping {year}-{month_str}"
        ):
            zf.write(full_path, arcname)

    print(f"Created: {output_zip}")
    return output_zip


def upload_to_huggingface():
    """Uploads all zips and metadata.json, syncing deletions."""
    api = HfApi()

    print("Starting upload to Hugging Face...")
    api.upload_folder(
        repo_id=HF_REPO_ID,
        folder_path=OUT_DIR,
        repo_type="dataset",
        token=HF_TOKEN,
        # Optional: ignore the raw unzipped folders, only upload zips and metadata
        delete_patterns=["*.json", "**/*.webp", "*.txt"],
        allow_patterns=["**/*.zip", "metadata.json.bz2", "published_images.txt.zip", "uploaded_at.txt"],
        commit_message=f"Sync dataset: {datetime.now().strftime('%Y-%m-%d %H:%M')}",
    )
    print("Upload complete.")


# -------------------------------------------
# Main Logic
# -------------------------------------------
def publish_period(metadata, start_dt, end_dt):
    new_metadata = publish_batch(start_dt, end_dt)
    metadata.update(new_metadata)
    return metadata


if __name__ == "__main__":
    # # copy_old_lsc_thumbnails()
    # metadata = {}
    # metadata = publish_period(metadata, datetime(2019, 1, 1), datetime(2020, 7, 1))
    # metadata = publish_period(metadata, datetime(2022, 1, 1), datetime(2022, 6, 1))
    # with open(os.path.join(OUT_DIR, "metadata.json"), "w") as f:
    #     json.dump(metadata, f, indent=4)

    # # # Verify
    # metadata_len = len(metadata)
    # print(f"Metadata entries: {metadata_len}")
    # files = glob.glob(os.path.join(OUT_DIR, "**/*.webp"), recursive=True)
    # print(f"Total images published: {len(files)}")
    # # Compress metadata with bzip2 for better compression ratios on large JSON files
    # print("Compressing metadata with bzip2...")
    # os.system(f"bzip2 -f {os.path.join(OUT_DIR, 'metadata.json')}")

    # # save list of published images for reference
    # with open(os.path.join(OUT_DIR, "published_images.txt"), "w") as f:
    #     files = sorted(metadata.keys())
    #     for file in files:
    #         f.write(f"{file}\n")

    # compress with password-protected published_images.txt
    with pyzipper.AESZipFile(
        os.path.join(OUT_DIR, "published_images.txt.zip"),
        "w",
        compression=pyzipper.ZIP_DEFLATED,
        compresslevel=1,
        encryption=pyzipper.WZ_AES,
    ) as zf:
        zf.setpassword(ZIP_PASSWORD.encode())
        zf.write(os.path.join(OUT_DIR, "published_images.txt"), "published_images.txt")

    # # delete existing zips to avoid duplicates and ensure clean uploads
    # if os.path.exists(OUT_DIR):
    #     for file in glob.glob(os.path.join(OUT_DIR, "**/*.zip"), recursive=True):
    #         os.remove(file)
    #         print(f"Deleted existing zip: {file}")
    # tasks = []
    # for year in range(2019, 2024):
    #     for month in range(1, 13):
    #         tasks.append((year, month, ZIP_PASSWORD))

    # with ProcessPoolExecutor(max_workers=os.cpu_count()) as executor:
    #     list(
    #         tqdm(
    #             executor.map(zip_monthly_data, tasks),
    #             total=len(tasks),
    #             desc="Zipping monthly data",
    #         )
    #     )

    # with open(os.path.join(OUT_DIR, "uploaded_at.txt"), "w") as f:
    #     f.write(f"Last uploaded at: {datetime.now().isoformat()}\n")

    # # Final Sync to Hugging Face
    upload_to_huggingface()

    # Squash lfs
    api = HfApi()
    api.super_squash_history(repo_id=HF_REPO_ID, repo_type="dataset", token=HF_TOKEN)

import os
import random
from collections import defaultdict

import numpy as np
from dotenv import load_dotenv
from PIL import Image as PILImage
from sqlalchemy import create_engine, select, update
from sqlalchemy.orm import Session
from tqdm import tqdm
from datetime import datetime

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


def index_image_sizes():
    with Session(engine) as session:
        sizes_to_id = defaultdict(list)
        stmt = select(Image).where(Image.width.is_(None))
        res = session.execute(stmt).scalars().all()
        for image in tqdm(res, desc="Indexing image sizes"):
            src_path = os.path.join(SRC_DIR, image.device, image.image_path)
            with PILImage.open(src_path) as img:
                width, height = img.size
                sizes_to_id[(width, height)].append(image.id)

        for size, ids in sizes_to_id.items():
            with Session(engine) as session:
                print(f"Updating {len(ids)} images to size {size}...")
                batch_size = 100
                for i in tqdm(
                    range(0, len(ids), batch_size), desc=f"Updating size {size}"
                ):
                    batch_ids = ids[i : i + batch_size]
                    stmt = (
                        update(Image)
                        .where(Image.id.in_(batch_ids))
                        .values(width=size[0], height=size[1])
                    )
                    session.execute(stmt)
                session.commit()


import os
from concurrent.futures import ProcessPoolExecutor

from PIL import Image as PILImage
from sqlalchemy import select
from tqdm import tqdm


# Define the worker function at the top level so it's pickleable for multiprocessing
def process_single_image(paths):
    src_path, thumb_path = paths
    try:
        if not os.path.exists(thumb_path):
            return f"Missing: {thumb_path}"

        with PILImage.open(src_path) as img:
            exif_dict = img.getexif()
            with PILImage.open(thumb_path) as thumb_img:
                # Note: Saving to the same path is generally safe with context managers
                thumb_img.save(thumb_path, "WEBP", exif=exif_dict)
        return None  # Success
    except Exception as e:
        return f"Error processing {src_path}: {e}"


def run_parallel_exif_copy(engine, SRC_DIR, THUMB_DIR):
    print("Gathering image paths...")
    pairs = []

    with Session(engine) as session:
        cutoff = "2020-01-07T00:00:00Z"
        stmt = select(Image).where(Image.timestamp > datetime.fromisoformat(cutoff))
        images = session.execute(stmt).scalars()

        for image in tqdm(images, desc="Preparing image pairs"):
            src_path = os.path.join(SRC_DIR, str(image.device), str(image.image_path))
            thumb_path = os.path.join(
                THUMB_DIR, str(image.device), str(image.thumbnail)
            )
            pairs.append((src_path, thumb_path))

    print(f"Copying EXIF data to {len(pairs)} thumbnails using multiprocessing...")

    # Use ProcessPoolExecutor to utilize multiple CPU cores
    CPU_COUNT = os.cpu_count() - 8
    with ProcessPoolExecutor(max_workers=CPU_COUNT) as executor:
        # list() forces the lazy map to execute, tqdm shows progress
        results = list(
            tqdm(executor.map(process_single_image, pairs), total=len(pairs))
        )

    # Optional: Print errors collected during processing
    errors = [r for r in results if r is not None]
    if errors:
        print(f"\nCompleted with {len(errors)} errors (check logs for details).")


if __name__ == "__main__":
    # index_image_sizes()
    run_parallel_exif_copy(engine, SRC_DIR, THUMB_DIR)

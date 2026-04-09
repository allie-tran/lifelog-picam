from pymongo import MongoClient
import glob
import os
from auth.ortho import get_matrix
from constants import DIR, THUMBNAIL_DIR
from pipelines.all import (
    create_thumbnail,
    encode_image,
    index_to_postgres,
    yolo_process_images,
)
from tqdm import tqdm
from PIL import Image as PILImage
from database.models import Image, ImageEmbedding
from sqlalchemy import delete, select


client = MongoClient("mongodb://localhost:27017/")
db = client["picam"]
mongo_collection = db["images"]


def to_id(image_path):
    return image_path.replace("/", "_")


def sync_images(session, device: str):
    print(f"Syncing images for device: {device}")

    # 1. Collect all the "databases"
    raw_images = glob.glob(f"{DIR}/{device}/**/*.jpg", recursive=True)
    raw_images = set(raw_images)
    raw_images = set(image.split(device + "/")[1] for image in raw_images)
    # raw_images = set(image for image in raw_images if "-" not in image.split("/")[-1])
    for image in raw_images.copy():
        if "-" in image.split("/")[-1]:
            os.remove(f"{DIR}/{device}/{image}")
            raw_images.remove(image)
    print(f"Total raw images: {len(raw_images)}")

    # 2. Start with missing in Postgres
    postgres_images = session.execute(
        select(Image.image_path).where(Image.device == device)
    ).fetchall()
    postgres_image_paths = set(image.image_path for image in postgres_images)
    print(f"Postgres: {len(postgres_image_paths)} images")
    missing_in_postgres = raw_images - postgres_image_paths
    print(f"Missing in Postgres: {len(missing_in_postgres)}")
    bad_images = set()
    for image in tqdm(missing_in_postgres, desc="Indexing to Postgres"):
        try:
            PILImage.open(f"{DIR}/{device}/{image}").verify()
        except Exception:
            print(f"Corrupted image found and removed: {DIR}/{device}/{image}")
            os.remove(f"{DIR}/{device}/{image}")
            bad_images.add(image)
            continue
        index_to_postgres(session, device, image, skip_segmentation=True)
    extra_in_postgres = postgres_image_paths - raw_images
    print(f"Extra in Postgres: {len(extra_in_postgres)}")
    session.execute(
        delete(Image).where(
            Image.device == device, Image.image_path.in_(extra_in_postgres)
        )
    )
    session.commit()
    print("-" * 30)

    # 3. Process missing in YOLO
    missing_in_yolo = session.execute(
        select(Image.image_path).where(Image.device == device, Image.proc_yolo == False)
    ).fetchall()
    missing_in_yolo = set(image.image_path for image in missing_in_yolo)
    missing_in_yolo = missing_in_yolo - bad_images
    missing_in_yolo = missing_in_yolo.intersection(raw_images)
    missing_in_yolo = sorted(missing_in_yolo, reverse=True)
    batch_size = 16
    whitelist = []
    for i in tqdm(range(0, len(missing_in_yolo), batch_size), desc="Processing YOLO"):
        batch = missing_in_yolo[i : i + batch_size]
        yolo_process_images(device, whitelist, batch)

    # 4. Check missing in thumbnail
    thumbnail_images = glob.glob(f"{THUMBNAIL_DIR}/{device}/**/*.webp", recursive=True)
    thumbnail_images = set(thumbnail_images)
    thumbnail_images = set(image.split(device + "/")[1] for image in thumbnail_images)
    thumbnail_images = set(image.replace(".webp", ".jpg") for image in thumbnail_images)
    print(f"Total thumbnail images: {len(thumbnail_images)}")
    missing_in_thumbnail = raw_images - thumbnail_images
    missing_in_thumbnail = missing_in_thumbnail - bad_images
    print(f"Missing in Thumbnail: {len(missing_in_thumbnail)}")
    missing_in_thumbnail = sorted(missing_in_thumbnail, reverse=True)
    for image in tqdm(missing_in_thumbnail, desc="Creating Thumbnails"):
        create_thumbnail(session, device, image)
    session.flush()

    # 5. Missing in embeddings
    embeddings_exists = session.execute(
        select(Image.image_path)
        .where(Image.device == device)
        .join(ImageEmbedding, Image.id == ImageEmbedding.image_id)
        .where(ImageEmbedding.image_id.isnot(None))
    ).scalars().all()
    missing_in_embeddings = raw_images - set(embeddings_exists)
    missing_in_embeddings = missing_in_embeddings - bad_images
    missing_in_embeddings = missing_in_embeddings.intersection(raw_images)
    missing_in_embeddings = sorted(missing_in_embeddings, reverse=True)

    matrix = get_matrix(session, device)
    for image in tqdm(missing_in_embeddings, desc="Encoding images"):
        encode_image(session, device, image, matrix)

    session.flush()
    # 6. Base on raw_images, find the extra ones in mongo and zvec
    extra_in_thumbnail = thumbnail_images - raw_images
    print(f"Extra in Thumbnail: {len(extra_in_thumbnail)}")
    for image in tqdm(extra_in_thumbnail):
        thumbnail_path = f"{THUMBNAIL_DIR}/{device}/{image.replace('.jpg', '.webp')}"
        if os.path.exists(thumbnail_path):
            os.remove(thumbnail_path)

    # extra_in_embedding = session.execute(
    #     select(Image.image_path)
    #     .where(Image.device == device)
    #     .where(ImageEmbedding.image_id.isnot(None))
    #     .join(ImageEmbedding, Image.id == ImageEmbedding.image_id)
    # ).fetchall()
    # extra_in_embedding = set(image.image_path for image in extra_in_embedding)
    # extra_in_embedding = extra_in_embedding - raw_images
    # print(f"Extra in Embeddings: {len(extra_in_embedding)}")
    # session.execute(
    #     delete(ImageEmbedding)
    #     .where(ImageEmbedding.image_id.in_(
    #         select(Image.id).where(Image.device == device, Image.image_path.in_(extra_in_embedding))
    #     ))
    # )

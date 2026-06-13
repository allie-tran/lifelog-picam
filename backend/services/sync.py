from pymongo import MongoClient
import glob
import os
from auth.ortho import get_matrix
from core.config import DIR, THUMBNAIL_DIR
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
from integrations.visual import clip_model


client = MongoClient("mongodb://localhost:27017/")
db = client["picam"]
mongo_collection = db["images"]


def to_id(image_path):
    return image_path.replace("/", "_")


def _stem(path: str) -> str:
    """Path without its file extension — the stable key shared by an original
    (.jpg or .webp) and its thumbnail (.webp)."""
    return path.rsplit(".", 1)[0]


def sync_images(session, device: str):
    print(f"Syncing images for device: {device}")

    # 1. Collect all the "databases" — originals may be .jpg (legacy) or .webp.
    raw_images = glob.glob(f"{DIR}/{device}/**/*.jpg", recursive=True) + glob.glob(
        f"{DIR}/{device}/**/*.webp", recursive=True
    )
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
            with PILImage.open(f"{DIR}/{device}/{image}") as _im:
                _im.verify()
        except Exception:
            print(f"Corrupted image found and removed: {DIR}/{device}/{image}")
            os.remove(f"{DIR}/{device}/{image}")
            bad_images.add(image)
            continue
        index_to_postgres(session, device, image, skip_segmentation=True)
    extra_in_postgres = postgres_image_paths - raw_images
    print(f"Extra in Postgres: {len(extra_in_postgres)}")
    batch_size = 2000
    extra_in_postgres = list(extra_in_postgres)
    for i in tqdm(range(0, len(extra_in_postgres), batch_size), desc="Removing extra in Postgres"):
        batch = extra_in_postgres[i : i + batch_size]
        session.execute(
            delete(Image).where(
                Image.device == device, Image.image_path.in_(batch)
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

    # 4. Check missing in thumbnail. Thumbnails are .webp keyed by stem; the
    # small grid derivatives (*_grid.webp) are not standalone thumbnails, so
    # exclude them or they'd be mistaken for orphans and deleted below.
    thumbnail_files = glob.glob(f"{THUMBNAIL_DIR}/{device}/**/*.webp", recursive=True)
    thumbnail_files = [t for t in thumbnail_files if not t.endswith("_grid.webp")]
    thumbnail_rel = set(t.split(device + "/")[1] for t in thumbnail_files)
    thumbnail_stems = set(_stem(t) for t in thumbnail_rel)
    print(f"Total thumbnail images: {len(thumbnail_stems)}")
    missing_in_thumbnail = set(img for img in raw_images if _stem(img) not in thumbnail_stems)
    missing_in_thumbnail = missing_in_thumbnail - bad_images
    print(f"Missing in Thumbnail: {len(missing_in_thumbnail)}")
    missing_in_thumbnail = sorted(missing_in_thumbnail, reverse=True)
    for image in tqdm(missing_in_thumbnail, desc="Creating Thumbnails"):
        create_thumbnail(session, device, image)
    session.flush()

    # 5. Missing in embeddings
    configs = [
        (ImageEmbedding, clip_model),
        # (CLIPEmbedding, openai_clip_model)
    ]
    for SQLTable, model in configs:
        embeddings_exists = session.execute(
            select(Image.image_path)
            .where(Image.device == device)
            .join(SQLTable, Image.id == SQLTable.image_id)
            .where(SQLTable.image_id.isnot(None))
        ).scalars().all()
        missing_in_embeddings = raw_images - set(embeddings_exists)
        missing_in_embeddings = missing_in_embeddings - bad_images
        missing_in_embeddings = missing_in_embeddings.intersection(raw_images)
        missing_in_embeddings = sorted(missing_in_embeddings, reverse=True)

        matrix = get_matrix(session, device)
        for image in tqdm(missing_in_embeddings, desc=f"Encoding images for {SQLTable.__tablename__}"):
            encode_image(session, device, image, matrix, SQLTable, model)
        session.flush()

    # 6. Base on raw_images, find the extra ones in mongo and zvec
    raw_stems = set(_stem(img) for img in raw_images)
    extra_thumbnail_stems = thumbnail_stems - raw_stems
    print(f"Extra in Thumbnail: {len(extra_thumbnail_stems)}")
    print(list(extra_thumbnail_stems)[:10])
    for stem in tqdm(extra_thumbnail_stems):
        for path in (
            f"{THUMBNAIL_DIR}/{device}/{stem}.webp",
            f"{THUMBNAIL_DIR}/{device}/{stem}_grid.webp",
        ):
            if os.path.exists(path):
                os.remove(path)

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

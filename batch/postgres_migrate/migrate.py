"""
migrate.py — MongoDB picam.images → PostgreSQL (SQLAlchemy)

Usage:
    python migrate.py

Requirements:
    pip install sqlalchemy psycopg[binary] pgvector pymongo
"""

import logging
from datetime import datetime, timezone
import pytz
from pymongo import MongoClient
from sqlalchemy import create_engine, text, select
from sqlalchemy.orm import Session
from sqlalchemy.dialects.postgresql import insert as pg_insert
import numpy as np
import pickle

from models import (
    Device,
    DeviceSecret,
    DeviceWhitelistEmbedding,
    DeviceWhitelistEntry,
    Location,
    Image,
    ImageEmbedding,
    CLIPEmbedding,
    ImageGPS,
    ImagePerson,
    ImageObject,
    ImageOCR,
)
from dotenv import load_dotenv
import os

load_dotenv()

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

MONGO_URI = "mongodb://localhost:27018/"
MONGO_DB = "picam"
MONGO_COL = "images"

PG_URI = os.getenv("PG_URI", "postgresql://postgres:password@localhost:5432/picam")

BATCH_SIZE = 500  # images flushed per session batch
EMBED_DIM = 512  # must match your face embedding model

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s")
log = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def resolve_double(val):
    """Handle MongoDB $numberDouble edge cases (Infinity, NaN)."""
    if isinstance(val, dict) and "$numberDouble" in val:
        s = val["$numberDouble"]
        return {"Infinity": float("inf"), "-Infinity": float("-inf")}.get(s, None)
    return val


def resolve_timestamp(val) -> datetime | None:
    if val is None:
        return None
    val = resolve_double(val)
    if val is None:
        return None
    try:
        val = float(val)
        if val > 1e12:
            val /= 1000  # convert ms to s if needed
        return datetime.fromtimestamp(val, tz=timezone.utc)
    except (ValueError, OSError):
        return None


def resolve_date(val) -> datetime | None:
    if isinstance(val, dict) and "$date" in val:
        return datetime.fromisoformat(val["$date"].replace("Z", "+00:00"))
    return None


matrices = {}


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


# ---------------------------------------------------------------------------
# Step 1: Export from MongoDB
# ---------------------------------------------------------------------------


def export_mongo() -> list[dict]:
    log.info("Connecting to MongoDB...")
    client = MongoClient(MONGO_URI)
    docs = list(client[MONGO_DB][MONGO_COL].find({"device": "allie"}))
    # docs += list(client[MONGO_DB][MONGO_COL].find({"device": "cathal"}).sort("timestamp", 1))
    log.info(f"Exported {len(docs)} documents")
    return docs


# ---------------------------------------------------------------------------
# Step 2: Migrate locations (deduplicated)
# ---------------------------------------------------------------------------
def create_key(fsq_place_id, name, country, address, is_stop):
    if fsq_place_id and fsq_place_id != "None":
        key = f"fsq_id={fsq_place_id}"
    else:
        key = f"{name}, {country}, {address}"
    key = f"stop={is_stop == 1}, {key}"
    return key

def migrate_locations(session: Session, docs: list[dict]) -> dict[str, str]:
    """
    Returns location_cache: dedup_key -> UUID string
    Uses ON CONFLICT upsert so re-runs are safe.
    Cities and regions are inserted as child rows (location_cities / location_regions).
    """
    log.info("Migrating locations...")
    location_cache: dict[str, str] = {}
    seen_keys: set[str] = set()

    for i, doc in enumerate(docs):
        loc = doc.get("location")
        if not loc:
            continue

        fsq_id = loc.get("fsq_id")
        key = create_key(
            fsq_place_id=fsq_id,
            name=loc.get("name", "Unknown Place"),
            country=loc.get("country", ""),
            address=loc.get("address", ""),
            is_stop=loc.get("stop", False),
        )
        if key in seen_keys:
            continue
        seen_keys.add(key)

        name = loc.get("name", "Unknown Place")
        if name == "Unknown Place":
            name = None  # to allow null for unique constraint if name is missing

        stmt = pg_insert(Location).values(
            key=key,
            name=name,
            country=loc.get("country"),
            fsq_id=fsq_id or None,  # Ensure null if falsy for unique constraint
            info=loc.get("info"),
            stop=loc.get("stop"),
            timezone=loc.get("timezone", "UTC"),
            address=loc.get("address", "") or None,
        )

        result = session.execute(stmt.returning(Location.id))
        row_id = str(result.scalar())
        location_cache[key] = row_id

        # Flush in batches to avoid memory buildup
        if (i + 1) % BATCH_SIZE == 0:
            session.flush()
            log.info(
                f"  → {i + 1}/{len(docs)} documents processed, {len(location_cache)} unique locations"
            )

    session.flush()
    log.info(f"  → {len(location_cache)} unique locations")
    return location_cache


# ---------------------------------------------------------------------------
# Step 3: Migrate images
# ---------------------------------------------------------------------------
def migrate_images(
    session: Session,
    docs: list[dict],
    location_cache: dict[str, str],
) -> dict[str, str]:
    """
    Returns mongo_to_pg: mongo _id str -> postgres UUID str
    """
    log.info("Migrating images...")
    mongo_to_pg: dict[str, str] = {}

    for i, doc in enumerate(docs):
        mongo_id = str(doc["_id"])

        # Resolve location
        loc = doc.get("location")
        location_id = None
        loc_timezone = timezone.utc
        if loc:
            fsq_id = loc.get("fsq_id")
            key = fsq_id if fsq_id else f"{loc.get('name')}::{loc.get('address')}"
            location_id = location_cache.get(key)
            loc_tz_str = loc.get("timezone", "UTC")
            loc_timezone = pytz.timezone(loc_tz_str) if loc_tz_str else timezone.utc

        time = resolve_timestamp(doc.get("timestamp"))
        assert (
            time is not None
        ), "Expected timestamp to be None or a valid number, got: {}".format(
            doc.get("timestamp")
        )

        local_timestamp = time.astimezone(loc_timezone)
        year, month, day, hour = (
            local_timestamp.year,
            local_timestamp.month,
            local_timestamp.day,
            local_timestamp.hour,
        )
        seconds_from_midnight = (
            local_timestamp.hour * 3600
            + local_timestamp.minute * 60
            + local_timestamp.second
        )

        processed = doc.get("processed", {})
        stmt = pg_insert(Image).values(
            mongo_id=mongo_id,
            image_path=doc["image_path"],
            thumbnail=doc["thumbnail"],
            is_video=doc["is_video"],
            timestamp=time,
            local_timestamp=local_timestamp,
            date=doc.get("date"),
            year=year,
            month=month,
            day=day,
            hour=hour,
            seconds_from_midnight=seconds_from_midnight,
            device=doc.get("device"),
            segment_id=doc.get("segment_id"),
            location_id=location_id,
            activity=doc.get("activity", ""),
            activity_confidence=doc.get("activity_confidence", ""),
            activity_description=doc.get("activity_description", ""),
            deleted=doc.get("deleted", False),
            deleted_time=resolve_timestamp(doc.get("deleted_time")),
            new=doc.get("new", False),
            proc_encoded=processed.get("encoded", False),
            proc_yolo=processed.get("yolo", False),
            proc_ocr=processed.get("ocr", False),
            proc_deepface=processed.get("deepface", False),
            proc_insightface=processed.get("insightface", False),
            proc_face_recognition=processed.get("face_recognition", False),
            proc_sam3=processed.get("sam3", False),
        )

        stmt.on_conflict_do_update(
            index_elements=["mongo_id"],
            set_={"image_path": stmt.excluded.image_path},
        )

        result = session.execute(stmt.returning(Image.id))
        mongo_to_pg[mongo_id] = str(result.scalar())

        # Flush in batches to avoid memory buildup
        if (i + 1) % BATCH_SIZE == 0:
            session.flush()
            log.info(f"  → {i + 1}/{len(docs)} images")

    session.flush()
    log.info(f"  → {len(mongo_to_pg)} images total")
    return mongo_to_pg


# ---------------------------------------------------------------------------
# Step: Migrate devices
# ---------------------------------------------------------------------------


def migrate_devices(session: Session, mongo_uri: str, mongo_db: str) -> dict[str, str]:
    """
    Reads from the 'devices' collection.
    Returns device_id_cache: device_id string -> postgres UUID string
    """
    import base64
    from pymongo import MongoClient

    log.info("Migrating devices...")
    client = MongoClient(mongo_uri)
    device_docs = list(client[mongo_db]["devices"].find())
    log.info(f"  Found {len(device_docs)} devices")

    device_id_cache: dict[str, str] = {}  # device_id str -> pg UUID

    for doc in device_docs:
        mongo_id = str(doc["_id"])
        device_id = doc["device_id"]

        # Decode transform_matrix from MongoDB $binary
        transform_matrix = None
        tm = doc.get("transform_matrix")
        if tm and isinstance(tm, dict) and "$binary" in tm:
            transform_matrix = base64.b64decode(tm["$binary"]["base64"])
        else:
            transform_matrix = tm

        matrices[device_id] = (
            pickle.loads(transform_matrix) if transform_matrix else None
        )

        stmt = pg_insert(Device).values(
            mongo_id=mongo_id,
            device_id=device_id,
            last_seen=resolve_date(doc.get("last_seen")),
            public_key=doc.get("public_key"),
        )
        insert_stmt = stmt.on_conflict_do_update(
            index_elements=["device_id"],
            set_={"last_seen": stmt.excluded.last_seen},
        )

        result = session.execute(insert_stmt.returning(Device.id))
        pg_device_id = str(result.scalar())
        device_id_cache[device_id] = pg_device_id

        # Store transform_matrix in isolated secrets table
        if transform_matrix is not None:
            secret_stmt = pg_insert(DeviceSecret).values(
                device_id=pg_device_id,
                transform_matrix=transform_matrix,
            )
            session.execute(
                secret_stmt.on_conflict_do_update(
                    index_elements=["device_id"],
                    set_={"transform_matrix": secret_stmt.excluded.transform_matrix},
                )
            )

        # Whitelist entries
        for entry in doc.get("whitelist", []):
            name = entry.get("name")
            if not name:
                continue

            entry_stmt = pg_insert(DeviceWhitelistEntry).values(
                device_id=pg_device_id,
                name=name,
                cropped=entry.get("cropped", []),
            )
            insert_entry_stmt = entry_stmt.on_conflict_do_update(
                constraint="uq_whitelist_device_name",
                set_={"cropped": entry_stmt.excluded.cropped},
            )

            entry_result = session.execute(
                insert_entry_stmt.returning(DeviceWhitelistEntry.id)
            )
            entry_pg_id = str(entry_result.scalar())

            # Embedding vectors
            emb_rows = []
            for emb in entry.get("embeddings", []):
                parsed = parse_embedding(emb) if isinstance(emb, (list, str)) else None
                if parsed:
                    emb_rows.append(
                        {
                            "entry_id": entry_pg_id,
                            "embedding": parsed,
                        }
                    )
            if emb_rows:
                session.execute(
                    pg_insert(DeviceWhitelistEmbedding)
                    .values(emb_rows)
                    .on_conflict_do_nothing()
                )

    session.flush()
    log.info(f"  → {len(device_id_cache)} devices migrated")
    return device_id_cache


def link_images_to_devices(session: Session, device_id_cache: dict[str, str]):
    """Update images.device_ref_id based on the device text field."""
    log.info("Linking images to devices...")
    for device_str, pg_device_id in device_id_cache.items():
        session.execute(
            text("UPDATE images SET device_ref_id = :did WHERE device = :dstr"),
            {"did": pg_device_id, "dstr": device_str},
        )
    session.flush()
    log.info("  → done")


# ---------------------------------------------------------------------------
# Step 4: Migrate child tables
# ---------------------------------------------------------------------------
def parse_embedding(emb) -> list[float] | None:
    """Normalise embedding to a float list regardless of how MongoDB stored it."""
    if emb is None:
        return None
    if isinstance(emb, str):
        import json

        emb = json.loads(emb)
    if isinstance(emb, list) and len(emb) == EMBED_DIM:
        return [float(x) for x in emb]
    return None  # wrong dimension or unexpected type


def migrate_people(session: Session, docs: list[dict], mongo_to_pg: dict[str, str]):
    log.info("Migrating people...")
    rows = []
    for i, doc in enumerate(docs):
        pg_id = mongo_to_pg.get(str(doc["_id"]))
        if not pg_id:
            continue
        for p in doc.get("people", []):
            rows.append(
                {
                    "image_id": pg_id,
                    "label": p.get("label"),
                    "confidence": p.get("confidence"),
                    "bbox": p.get("bbox"),
                    "cluster_label": p.get("cluster_label"),
                    "embedding": parse_embedding(p.get("embedding")),
                }
            )

        # Flush in batches to avoid memory buildup
        if len(rows) >= BATCH_SIZE:
            if rows:
                session.execute(
                    pg_insert(ImagePerson).values(rows).on_conflict_do_nothing()
                )
                rows.clear()
            session.flush()
            log.info(f"  → {i + 1}/{len(docs)} documents processed for people")

    if rows:
        session.execute(pg_insert(ImagePerson).values(rows).on_conflict_do_nothing())
    log.info(f"  → {len(rows)} people detections")


def migrate_objects(session: Session, docs: list[dict], mongo_to_pg: dict[str, str]):
    log.info("Migrating objects...")
    rows = []
    for i, doc in enumerate(docs):
        pg_id = mongo_to_pg.get(str(doc["_id"]))
        if not pg_id:
            continue
        for o in doc.get("objects", []):
            rows.append(
                {
                    "image_id": pg_id,
                    "label": o.get("label"),
                    "confidence": o.get("confidence"),
                    "bbox": o.get("bbox"),
                }
            )

        # Flush in batches to avoid memory buildup
        if len(rows) >= BATCH_SIZE:
            if rows:
                session.execute(
                    pg_insert(ImageObject).values(rows).on_conflict_do_nothing()
                )
                rows.clear()
            session.flush()
            log.info(f"  → {i + 1}/{len(docs)} documents processed for objects")

    if rows:
        session.execute(pg_insert(ImageObject).values(rows).on_conflict_do_nothing())
    log.info(f"  → {len(rows)} object detections")


def migrate_ocr(session: Session, docs: list[dict], mongo_to_pg: dict[str, str]):
    BATCH_OCR_SIZE = 1000
    log.info("Migrating OCR...")
    rows = []
    for i, doc in enumerate(docs):
        pg_id = mongo_to_pg.get(str(doc["_id"]))
        if not pg_id:
            continue
        for o in doc.get("ocr", []):
            geom = o.get("geometry", {})
            text = o.get("text", "")
            rows.append(
                {
                    "image_id": pg_id,
                    "text": text,
                    "confidence": o.get("confidence"),
                    "box_2d": geom.get("box_2d"),
                    # "polygon":    geom.get("polygon"),
                }
            )

        # Flush in batches to avoid memory buildup
        if len(rows) >= BATCH_OCR_SIZE:
            session.execute(pg_insert(ImageOCR).values(rows).on_conflict_do_nothing())
            session.flush()
            rows.clear()
            log.info(f"  → {i + 1}/{len(docs)} documents processed for OCR")

    if rows:
        session.execute(pg_insert(ImageOCR).values(rows).on_conflict_do_nothing())
    log.info(f"  → {len(rows)} OCR entries")


def migrate_gps(session: Session, docs: list[dict], mongo_to_pg: dict[str, str]):
    log.info("Migrating GPS...")
    rows = []
    for i, doc in enumerate(docs):
        pg_id = mongo_to_pg.get(str(doc["_id"]))
        if not pg_id or not doc.get("gps"):
            continue
        g = doc["gps"]
        lat = resolve_double(g["latitude"])
        lon = resolve_double(g["longitude"])
        rows.append(
            {
                "image_id": pg_id,
                "latitude": lat,
                "longitude": lon,
                "elevation": resolve_double(g.get("elevation")),
                "timestamp": resolve_double(g.get("timestamp")),
                "formatted_time": g.get("formatted_time"),
                "satellites": g.get("satellites"),
                "source": g.get("source"),
                "gap_s": resolve_double(g.get("gap_s")),
                # PostGIS WKT — note longitude comes first in WGS84
                "geog": f"SRID=4326;POINT({lon} {lat})" if lat and lon else None,
            }
        )

        # Flush in batches to avoid memory buildup
        if len(rows) >= BATCH_SIZE:
            if rows:
                session.execute(
                    pg_insert(ImageGPS).values(rows).on_conflict_do_nothing()
                )
                rows.clear()
            session.flush()
            log.info(f"  → {i + 1}/{len(docs)} documents processed for GPS")

    if rows:
        session.execute(pg_insert(ImageGPS).values(rows).on_conflict_do_nothing())
    log.info(f"  → {len(rows)} GPS entries")


# ---------------------------------------------------------------------------
#  Migrate embeddings (from .npy files)
# ---------------------------------------------------------------------------

EMBEDDING_DIR = "/mnt/ssd0/embeddings/cathal/vitl14336"
IMAGE_EMBED_DIM = 768


def migrate_embeddings(session: Session):
    """Load .npy image embeddings from EMBEDDING_DIR and UPDATE directly onto images rows."""
    import os
    import numpy as np

    log.info("Migrating image embeddings...")
    if not os.path.isdir(EMBEDDING_DIR):
        log.warning(f"  EMBEDDING_DIR not found: {EMBEDDING_DIR} — skipping")
        return

    missing = 0
    wrong_dim = 0
    total = 0

    res = session.execute(select(Image.id, Image.image_path, Image.device))
    rows = []
    for r in res.all():
        image_path = r.image_path
        device_id = r.device
        pg_id = r.id

        basename = os.path.basename(image_path)
        # npy_path = os.path.join(
        #     EMBEDDING_DIR, f"{device_id}_features", f"{basename}.npy"
        # )
        npy_path = os.path.join(
            EMBEDDING_DIR, f"{basename}.npy"
        )
        matrix = None
        if device_id != "allie":  # allie's embeddings are already transformed
            matrix = matrices.get(device_id)

        if not os.path.exists(npy_path):
            missing += 1
            continue

        emb = np.load(npy_path).flatten()
        emb = apply_transformation(emb, matrix)
        emb = emb.tolist()

        if len(emb) != IMAGE_EMBED_DIM:
            wrong_dim += 1
            continue

        rows.append({
            "image_id": pg_id,
            "embedding": emb,
        })
        total += 1

        # Flush in batches to avoid memory buildup (embeddings can be large)
        if len(rows) >= 100:
            session.execute(
                pg_insert(CLIPEmbedding).values(rows).on_conflict_do_nothing()
            )
            session.commit()
            session.flush()
            rows.clear()
            log.info(f"    flushed {total} embeddings...")

    if missing:
        log.warning(f"  {missing} images had no .npy file")
    if wrong_dim:
        log.warning(
            f"  {wrong_dim} embeddings had wrong dimension (expected {IMAGE_EMBED_DIM})"
        )

    session.flush()
    log.info(f"  → {total} image embeddings loaded")


# ---------------------------------------------------------------------------
# Step 5: Build indexes (after bulk load)
# ---------------------------------------------------------------------------

INDEXES = [
    # images
    "CREATE INDEX IF NOT EXISTS ix_images_timestamp     ON images (timestamp)",
    "CREATE INDEX IF NOT EXISTS ix_images_date          ON images (date)",
    "CREATE INDEX IF NOT EXISTS ix_images_segment       ON images (segment_id)",
    "CREATE INDEX IF NOT EXISTS ix_images_location      ON images (location_id)",
    "CREATE INDEX IF NOT EXISTS ix_images_path          ON images (image_path)",
    "CREATE INDEX IF NOT EXISTS ix_images_device        ON images (device)",
    "CREATE INDEX IF NOT EXISTS ix_images_deleted       ON images (deleted)",
    "CREATE INDEX IF NOT EXISTS ix_images_deleted_time  ON images (deleted_time)",
    # embeddings
    "CREATE INDEX IF NOT EXISTS ix_embeddings           ON image_embedding USING hnsw (embedding vector_cosine_ops)",
    # devices
    "CREATE INDEX IF NOT EXISTS ix_devices_device_id    ON devices (device_id)",
    "CREATE INDEX IF NOT EXISTS ix_whitelist_device     ON device_whitelist (device_id)",
    "CREATE INDEX IF NOT EXISTS ix_whitelist_emb_entry  ON device_whitelist_embeddings (entry_id)",
    "CREATE INDEX IF NOT EXISTS ix_whitelist_emb_hnsw   ON device_whitelist_embeddings USING hnsw (embedding vector_cosine_ops)",
    "CREATE INDEX IF NOT EXISTS ix_images_device_ref    ON images (device_ref_id)",
    # people — HNSW for ANN search
    "CREATE INDEX IF NOT EXISTS ix_people_image       ON image_people (image_id)",
    "CREATE INDEX IF NOT EXISTS ix_people_cluster     ON image_people (cluster_label)",
    "CREATE INDEX IF NOT EXISTS ix_people_embedding   ON image_people USING hnsw (embedding vector_cosine_ops)",
    # objects
    "CREATE INDEX IF NOT EXISTS ix_objects_image      ON image_objects (image_id)",
    "CREATE INDEX IF NOT EXISTS ix_objects_label      ON image_objects (label)",
    # ocr — full-text search
    "CREATE INDEX IF NOT EXISTS ix_ocr_image          ON image_ocr (image_id)",
    "CREATE INDEX IF NOT EXISTS ix_ocr_fts            ON image_ocr USING gin (to_tsvector('english', coalesce(text,'')))",
    # gps — spatial index (GIST on Geography enables ST_DWithin, ST_Distance etc.)
    "CREATE INDEX IF NOT EXISTS ix_gps_image          ON image_gps (image_id)",
    "CREATE INDEX IF NOT EXISTS ix_gps_geog           ON image_gps USING gist (geog)",
]


def build_indexes(session: Session):
    log.info("Building indexes...")
    for stmt in INDEXES:
        session.execute(text(stmt))
    log.info("  → done")


# ---------------------------------------------------------------------------
# Step 6: Verify
# ---------------------------------------------------------------------------


def verify(session: Session, docs: list[dict]):
    log.info("Verifying...")

    def count(model):
        return session.execute(
            text(f"SELECT COUNT(*) FROM {model.__tablename__}")
        ).scalar()

    checks = {
        "images": (count(Image), len(docs)),
        "image_people": (
            count(ImagePerson),
            sum(len(d.get("people", [])) for d in docs),
        ),
        "image_objects": (
            count(ImageObject),
            sum(len(d.get("objects", [])) for d in docs),
        ),
        "image_ocr": (count(ImageOCR), sum(len(d.get("ocr", [])) for d in docs)),
        "image_gps": (count(ImageGPS), sum(1 for d in docs if d.get("gps"))),
    }

    all_ok = True
    for table, (pg_n, mongo_n) in checks.items():
        status = "✓" if pg_n == mongo_n else "✗"
        log.info(f"  {status} {table}: pg={pg_n}, mongo={mongo_n}")
        if pg_n != mongo_n:
            all_ok = False

    if not all_ok:
        raise RuntimeError("Verification failed — check logs above")
    log.info("All counts match ✓")


# ---------------------------------------------------------------------------
# Entrypoint
# ---------------------------------------------------------------------------


def main():
    engine = create_engine(PG_URI, echo=False, pool_pre_ping=True)

    # delete_all = (
    #     True  # set to True to wipe existing data before migration (use with caution!)
    # )
    # if delete_all:
    #     with Session(engine) as session:
    #         session.execute(text("DROP SCHEMA public CASCADE"))
    #         session.execute(text("CREATE SCHEMA public AUTHORIZATION postgres"))
    #         session.commit()
    #     log.info("Deleted existing data from PostgreSQL")

    # # Enable pgvector extension and create tables
    # with engine.connect() as conn:
    #     conn.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))
    #     conn.execute(text("CREATE EXTENSION IF NOT EXISTS postgis"))
    #     conn.commit()

    # Base.metadata.create_all(engine)

    # Export once
    docs = export_mongo()

    # Filter out documents that are already in Postgres (based on mongo_id) to allow safe re-runs without duplicates
    with Session(engine) as session:
        existing_ids = set(
            session.execute(text("SELECT mongo_id FROM images")).scalars().all()
        )
    docs = [d for d in docs if str(d["_id"]) not in existing_ids]
    mongo_to_pg = {}

    # Migrate in a single transaction — rolls back entirely on failure
    with Session(engine) as session:
        # device_id_cache = migrate_devices(session, MONGO_URI, MONGO_DB)
        # location_cache = migrate_locations(session, docs)
        # mongo_to_pg = migrate_images(session, docs, location_cache)
        migrate_embeddings(session)
        # migrate_people(session, docs, mongo_to_pg)
        # migrate_objects(session, docs, mongo_to_pg)
        # migrate_gps(session, docs, mongo_to_pg)
        # migrate_ocr(session, docs, mongo_to_pg)

        # link_images_to_devices(session, device_id_cache)
        # Indexes outside transaction (DDL can't be rolled back in PG anyway)
        session.commit()

    with Session(engine) as session:
        build_indexes(session)
        session.commit()

    # with Session(engine) as session:
    #     verify(session, docs)


if __name__ == "__main__":
    main()

"""
search_test.py — Test queries for the picam PostgreSQL database

Usage:
    python search_test.py          # all tests
    python search_test.py vector   # image similarity
    python search_test.py face     # face similarity + cluster
    python search_test.py ocr      # full-text + exact match
    python search_test.py gps      # proximity + bounding box
    python search_test.py date     # year/month/weekday/hour distributions
"""

import sys
import logging
from sqlalchemy import and_, create_engine, select, func, cast, Float
from sqlalchemy.orm import Session
from geoalchemy2 import Geography
from geoalchemy2.functions import ST_DWithin, ST_Distance, ST_MakePoint

from models import Image, ImageEmbedding, ImagePerson, ImageOCR, ImageGPS, Location

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

PG_URI      = "postgresql+psycopg://postgres:lsc26@localhost/picam"
TOP_K        = 10
GPS_RADIUS_M = 500

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s")
log = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def print_results(label: str, rows):
    print(f"\n{'='*60}")
    print(f"  {label}")
    print(f"{'='*60}")
    if not rows:
        print("  (no results)")
        return
    for row in rows:
        print(f"  {dict(row._mapping)}")


def get_sample_image_embedding(session: Session):
    return session.execute(
        select(ImageEmbedding.embedding)
        .where(ImageEmbedding.embedding.isnot(None))
        .limit(1)
    ).scalar()


def get_sample_face_embedding(session: Session):
    return session.execute(
        select(ImagePerson.embedding)
        .where(ImagePerson.embedding.isnot(None))
        .limit(1)
    ).scalar()


def get_sample_gps(session: Session):
    row = session.execute(
        select(ImageGPS.latitude, ImageGPS.longitude).limit(1)
    ).fetchone()
    return (row.latitude, row.longitude) if row else None


# ---------------------------------------------------------------------------
# 1. Vector similarity — scene/content search on image embeddings
# ---------------------------------------------------------------------------

def test_vector_similarity(session: Session, sort_by_timestamp: bool = False):
    log.info("Testing vector similarity search...")

    emb = get_sample_image_embedding(session)
    if emb is None:
        log.warning("  No image embeddings found — skipping")
        return

    # show only image_path
    rows = session.execute(
        select(
            ImageEmbedding.image_id,
            Image,
            ImageEmbedding.embedding.cosine_distance(emb).label("distance"),
        )
        .where(and_(ImageEmbedding.embedding.isnot(None), Image.deleted == False))
        .order_by(Image.timestamp.desc() if sort_by_timestamp else ImageEmbedding.embedding.cosine_distance(emb))
        .join(Image, Image.id == ImageEmbedding.image_id)
        .limit(TOP_K)

    ).fetchall()

    print_results(f"Vector similarity (top {TOP_K}, using first DB embedding as query)", rows)
    # distance = 0.0 should be the query image itself


# ---------------------------------------------------------------------------
# 2. Face similarity
# ---------------------------------------------------------------------------

def test_face_similarity(session: Session):
    log.info("Testing face similarity search...")

    emb = get_sample_face_embedding(session)
    if emb is None:
        log.warning("  No face embeddings found — skipping")
        return

    rows = session.execute(
        select(
            ImagePerson.image_id,
            Image.image_path,
            ImagePerson.label,
            ImagePerson.confidence,
            ImagePerson.embedding.cosine_distance(emb).label("face_distance"),
        )
        .join(Image, Image.id == ImagePerson.image_id)
        .where(ImagePerson.embedding.isnot(None))
        .order_by(ImagePerson.embedding.cosine_distance(emb))
        .limit(TOP_K)
    ).fetchall()

    print_results(f"Face similarity (top {TOP_K})", rows)


def test_face_by_cluster(session: Session):
    log.info("Testing face cluster search...")

    # Find the largest cluster
    top_cluster = session.execute(
        select(
            ImagePerson.cluster_label,
            func.count().label("cnt"),
        )
        .where(ImagePerson.cluster_label.isnot(None))
        .group_by(ImagePerson.cluster_label)
        .order_by(func.count().desc())
        .limit(1)
    ).fetchone()

    if not top_cluster:
        log.warning("  No cluster labels found — skipping")
        return

    cluster_id, cnt = top_cluster.cluster_label, top_cluster.cnt

    rows = session.execute(
        select(
            ImagePerson.image_id,
            Image.image_path,
            Image.date,
            ImagePerson.label,
            ImagePerson.confidence,
        )
        .join(Image, Image.id == ImagePerson.image_id)
        .where(ImagePerson.cluster_label == cluster_id)
        .order_by(Image.timestamp)
        .limit(TOP_K)
    ).fetchall()

    print_results(f"Face cluster search (cluster_label={cluster_id}, {cnt} total members)", rows)


# ---------------------------------------------------------------------------
# 3. OCR full-text and exact search
# ---------------------------------------------------------------------------

def test_ocr_search(session: Session):
    log.info("Testing OCR full-text search...")

    # Find the most common word in OCR text to use as test query
    top_word = session.execute(
        select(func.lower(ImageOCR.text).label("word"), func.count().label("cnt"))
        .where(ImageOCR.text.isnot(None))
        .where(func.length(ImageOCR.text) > 3)
        .group_by(func.lower(ImageOCR.text))
        .order_by(func.count().desc())
        .limit(1)
    ).fetchone()

    if not top_word:
        log.warning("  No OCR text found — skipping")
        return

    query_word = top_word.word
    log.info(f"  Using most common OCR word: '{query_word}' ({top_word.cnt} occurrences)")

    ts_query  = func.plainto_tsquery("english", query_word)
    ts_vector = func.to_tsvector("english", ImageOCR.text)
    ts_rank   = func.ts_rank(ts_vector, ts_query).label("rank")

    rows = session.execute(
        select(
            ImageOCR.image_id,
            Image.image_path,
            Image.date,
            ImageOCR.text,
            ImageOCR.confidence,
            ts_rank,
        )
        .join(Image, Image.id == ImageOCR.image_id)
        .where(ts_vector.op("@@")(ts_query))
        .order_by(ts_rank.desc())
        .limit(TOP_K)
    ).fetchall()

    print_results(f"OCR full-text search for '{query_word}' (top {TOP_K})", rows)


def test_ocr_exact(session: Session, query: str = None):
    log.info("Testing OCR exact/partial search...")

    if not query:
        row = session.execute(
            select(ImageOCR.text)
            .where(ImageOCR.text.isnot(None))
            .where(func.length(ImageOCR.text).between(3, 10))
            .limit(1)
        ).scalar()
        if not row:
            log.warning("  No short OCR text found — skipping")
            return
        query = row.strip()

    log.info(f"  Searching for: '{query}'")

    rows = session.execute(
        select(
            ImageOCR.image_id,
            Image.image_path,
            Image.date,
            ImageOCR.text,
            ImageOCR.confidence,
        )
        .join(Image, Image.id == ImageOCR.image_id)
        .where(ImageOCR.text.ilike(f"%{query}%"))
        .order_by(ImageOCR.confidence.desc())
        .limit(TOP_K)
    ).fetchall()

    print_results(f"OCR exact match for '%{query}%'", rows)


# ---------------------------------------------------------------------------
# 4. GPS proximity and bounding box
# ---------------------------------------------------------------------------

def test_gps_proximity(session: Session):
    log.info("Testing GPS proximity search...")

    coords = get_sample_gps(session)
    if not coords:
        log.warning("  No GPS data found — skipping")
        return

    lat, lon = coords
    log.info(f"  Searching within {GPS_RADIUS_M}m of ({lat:.4f}, {lon:.4f})")

    point = func.cast(ST_MakePoint(lon, lat), Geography)

    rows = session.execute(
        select(
            Image.id,
            Image.image_path,
            Image.date,
            ImageGPS.latitude,
            ImageGPS.longitude,
            ST_Distance(ImageGPS.geog, point).label("dist_m"),
        )
        .join(Image, Image.id == ImageGPS.image_id)
        .where(ST_DWithin(ImageGPS.geog, point, GPS_RADIUS_M))
        .order_by(ST_Distance(ImageGPS.geog, point))
        .limit(TOP_K)
    ).fetchall()

    print_results(f"GPS proximity (within {GPS_RADIUS_M}m, top {TOP_K})", rows)


def test_gps_bounding_box(session: Session):
    log.info("Testing GPS bounding box search...")

    coords = get_sample_gps(session)
    if not coords:
        log.warning("  No GPS data found — skipping")
        return

    lat, lon = coords
    delta = 0.01  # ~1km

    rows = session.execute(
        select(
            Image.id,
            Image.image_path,
            Image.date,
            ImageGPS.latitude,
            ImageGPS.longitude,
        )
        .join(Image, Image.id == ImageGPS.image_id)
        .where(ImageGPS.latitude.between(lat - delta, lat + delta))
        .where(ImageGPS.longitude.between(lon - delta, lon + delta))
        .order_by(Image.timestamp)
        .limit(TOP_K)
    ).fetchall()

    print_results(f"GPS bounding box (~1km around first GPS point)", rows)


# ---------------------------------------------------------------------------
# 5. Date / time filters
# ---------------------------------------------------------------------------

def test_date_filters(session: Session):
    log.info("Testing date/time filters...")

    years = session.execute(
        select(Image.year)
        .where(Image.year.isnot(None))
        .distinct()
        .order_by(Image.year)
    ).scalars().all()

    if not years:
        log.warning("  No year data found — skipping")
        return

    sample_year = years[0]
    log.info(f"  Available years: {years}")

    # Images from first year
    rows = session.execute(
        select(Image.id, Image.image_path, Image.date, Image.hour)
        .where(Image.year == sample_year)
        .order_by(Image.timestamp)
        .limit(TOP_K)
    ).fetchall()
    print_results(f"Images from year {sample_year} (first {TOP_K})", rows)

    # Count by month within year
    rows = session.execute(
        select(Image.month, func.count().label("image_count"))
        .where(Image.year == sample_year)
        .group_by(Image.month)
        .order_by(Image.month)
    ).fetchall()
    print_results(f"Image count by month in {sample_year}", rows)

    # Count by day of week
    rows = session.execute(
        select(
            func.to_char(Image.timestamp, "Day").label("weekday"),
            func.count().label("image_count"),
        )
        .where(Image.timestamp.isnot(None))
        .group_by(func.to_char(Image.timestamp, "Day"))
        .order_by(func.min(func.extract("dow", Image.timestamp)))
    ).fetchall()
    print_results("Image count by day of week", rows)

    # Count by hour
    rows = session.execute(
        select(Image.hour, func.count().label("image_count"))
        .where(Image.hour.isnot(None))
        .group_by(Image.hour)
        .order_by(cast(Image.hour, Float))
    ).fetchall()
    print_results("Image count by hour of day", rows)


# ---------------------------------------------------------------------------
# Entrypoint
# ---------------------------------------------------------------------------

TESTS = {
    "vector": [test_vector_similarity, lambda session: test_vector_similarity(session, sort_by_timestamp=True)],
    "face":   [test_face_similarity, test_face_by_cluster],
    "ocr":    [test_ocr_search, test_ocr_exact],
    "gps":    [test_gps_proximity, test_gps_bounding_box],
    "date":   [test_date_filters],
}


def main():
    engine = create_engine(PG_URI, echo=False)

    with Session(engine) as session:
        images   = session.execute(select(func.count()).select_from(Image)).scalar()
        people   = session.execute(select(func.count()).select_from(ImagePerson)).scalar()
        ocr      = session.execute(select(func.count()).select_from(ImageOCR)).scalar()
        gps      = session.execute(select(func.count()).select_from(ImageGPS)).scalar()
        log.info(f"DB — images: {images}, people: {people}, ocr: {ocr}, gps: {gps}")

    filter_key = sys.argv[1].lower() if len(sys.argv) > 1 else None
    if filter_key and filter_key not in TESTS:
        print(f"Unknown test '{filter_key}'. Choose from: {', '.join(TESTS)}")
        sys.exit(1)

    selected = {filter_key: TESTS[filter_key]} if filter_key else TESTS

    with Session(engine) as session:
        for key, fns in selected.items():
            for fn in fns:
                try:
                    fn(session)
                except Exception as e:
                    log.error(f"  {fn.__name__} failed: {e}", exc_info=True)


if __name__ == "__main__":
    main()

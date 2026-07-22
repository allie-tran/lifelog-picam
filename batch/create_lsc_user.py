"""
Create a new device "LSC" and copy all images (+ child records) from device "cathal"
taken before 2020-07-01.

Tables copied:
  images            — new UUIDs, device='LSC', mongo_id cleared
  image_gps         — new UUIDs, remapped image_id
  image_embedding   — remapped image_id (image_id IS the PK)
  clip_embedding    — remapped image_id (image_id IS the PK)
  image_objects     — new UUIDs, remapped image_id
  image_ocr         — new UUIDs, remapped image_id
  image_people      — new UUIDs, remapped image_id, cluster_id=NULL
  annotations       — new UUIDs, remapped image_id

Tables NOT copied:
  raw_gps, people_clusters, device_whitelist* — device-level, not per-image
  bio_* — health data linked by device string, not image
"""

import sys
import os
import shutil
import psycopg2
from psycopg2.extras import RealDictCursor
from dotenv import load_dotenv
from pathlib import Path

load_dotenv(Path(__file__).parent.parent / "backend" / ".env")

PG_URI      = os.environ["PG_URI"]
DIR         = Path(os.environ["DIR"])
THUMB_DIR   = Path(os.environ["THUMBNAIL_DIR"])
SOURCE_DEVICE = "cathal"
TARGET_DEVICE = "LSC"
CUTOFF = "2020-07-01"


def link_or_copy(src: Path, dst: Path) -> str:
    """Hard-link if possible (same device), otherwise copy. Returns 'link' or 'copy'."""
    dst.parent.mkdir(parents=True, exist_ok=True)
    if dst.exists():
        return "skip"
    try:
        os.link(src, dst)
        return "link"
    except OSError:
        shutil.copy2(src, dst)
        return "copy"


def copy_files(paths: list[tuple[str, str]]) -> None:
    """
    paths: list of (image_path, thumbnail) relative strings, e.g. ('2019-11-23/img.jpg', '2019-11-23/img.webp')
    Copies/links both from SOURCE_DEVICE dirs into TARGET_DEVICE dirs.
    """
    src_img_root   = DIR       / SOURCE_DEVICE
    dst_img_root   = DIR       / TARGET_DEVICE
    src_thumb_root = THUMB_DIR / SOURCE_DEVICE
    dst_thumb_root = THUMB_DIR / TARGET_DEVICE

    counts = {"link": 0, "copy": 0, "skip": 0, "missing": 0}

    for i, (img_rel, thumb_rel) in enumerate(paths):
        for src_root, dst_root, rel in [
            (src_img_root,   dst_img_root,   img_rel),
            (src_thumb_root, dst_thumb_root, thumb_rel),
        ]:
            src = src_root / rel
            dst = dst_root / rel
            if not src.exists():
                counts["missing"] += 1
                print(f"  MISSING: {src}", file=sys.stderr)
                continue
            result = link_or_copy(src, dst)
            counts[result] += 1

        if (i + 1) % 1000 == 0:
            print(f"  {i + 1}/{len(paths)} files processed …")

    print(f"  Files — linked:{counts['link']}  copied:{counts['copy']}  skipped:{counts['skip']}  missing:{counts['missing']}")


def run():
    conn = psycopg2.connect(PG_URI)
    conn.autocommit = False
    cur = conn.cursor(cursor_factory=RealDictCursor)

    try:
        # ── 1. Ensure target device exists ────────────────────────────────────
        cur.execute(
            """
            INSERT INTO devices (id, device_id, keep_face_recognition)
            VALUES (gen_random_uuid(), %s, FALSE)
            ON CONFLICT (device_id) DO NOTHING
            """,
            (TARGET_DEVICE,),
        )
        cur.execute("SELECT id FROM devices WHERE device_id = %s", (TARGET_DEVICE,))
        row = cur.fetchone()
        assert row, f"Device '{TARGET_DEVICE}' not found after insert"
        lsc_device_id = row["id"]
        print(f"LSC device id: {lsc_device_id}")

        # ── 2. Temp mapping: old image id → new image id ──────────────────────
        cur.execute(
            """
            CREATE TEMP TABLE _image_map AS
            SELECT id AS old_id, gen_random_uuid() AS new_id, image_path, thumbnail
            FROM images
            WHERE device = %s
              AND timestamp < %s
              AND (deleted IS FALSE OR deleted IS NULL)
            """,
            (SOURCE_DEVICE, CUTOFF),
        )
        cur.execute("SELECT COUNT(*) AS n FROM _image_map")
        count_row = cur.fetchone()
        n = count_row["n"] if count_row else 0
        print(f"Images to copy: {n}")
        if n == 0:
            print("Nothing to copy — check source device name and date filter.")
            conn.rollback()
            return

        # Collect paths now (temp table gone after commit)
        cur.execute("SELECT image_path, thumbnail FROM _image_map")
        file_paths = [(r["image_path"], r["thumbnail"]) for r in cur.fetchall()]

        # ── 3. Copy images ────────────────────────────────────────────────────
        cur.execute(
            """
            INSERT INTO images (
                id, image_path, thumbnail, is_video, timestamp, local_timestamp,
                timezone, date, year, month, day, hour, seconds_from_midnight,
                device, device_ref_id,
                segment_id, location_id,
                activity, activity_group, activity_confidence, activity_description, activity_tags,
                deleted, new,
                proc_encoded, proc_yolo, proc_ocr, proc_deepface,
                proc_insightface, proc_face_recognition, proc_sam3,
                width, height
            )
            SELECT
                m.new_id, i.image_path, i.thumbnail, i.is_video, i.timestamp, i.local_timestamp,
                i.timezone, i.date, i.year, i.month, i.day, i.hour, i.seconds_from_midnight,
                %s, %s,
                i.segment_id, i.location_id,
                i.activity, i.activity_group, i.activity_confidence, i.activity_description, i.activity_tags,
                i.deleted, i.new,
                i.proc_encoded, i.proc_yolo, i.proc_ocr, i.proc_deepface,
                i.proc_insightface, i.proc_face_recognition, i.proc_sam3,
                i.width, i.height
            FROM images i
            JOIN _image_map m ON i.id = m.old_id
            """,
            (TARGET_DEVICE, lsc_device_id),
        )
        print(f"  images: {cur.rowcount} rows inserted")

        # ── 4. Copy image_gps ─────────────────────────────────────────────────
        cur.execute(
            """
            INSERT INTO image_gps (
                id, image_id, latitude, longitude, elevation, timestamp,
                formatted_time, satellites, source, gap_s, interpolated, timezone, geog
            )
            SELECT
                gen_random_uuid(), m.new_id,
                g.latitude, g.longitude, g.elevation, g.timestamp,
                g.formatted_time, g.satellites, g.source, g.gap_s, g.interpolated, g.timezone, g.geog
            FROM image_gps g
            JOIN _image_map m ON g.image_id = m.old_id
            """
        )
        print(f"  image_gps: {cur.rowcount} rows inserted")

        # ── 5. Copy image_embedding (image_id IS the PK) ──────────────────────
        cur.execute(
            """
            INSERT INTO image_embedding (image_id, embedding)
            SELECT m.new_id, e.embedding
            FROM image_embedding e
            JOIN _image_map m ON e.image_id = m.old_id
            """
        )
        print(f"  image_embedding: {cur.rowcount} rows inserted")

        # ── 6. Copy clip_embedding ────────────────────────────────────────────
        cur.execute(
            """
            INSERT INTO clip_embedding (image_id, embedding)
            SELECT m.new_id, e.embedding
            FROM clip_embedding e
            JOIN _image_map m ON e.image_id = m.old_id
            """
        )
        print(f"  clip_embedding: {cur.rowcount} rows inserted")

        # ── 7. Copy image_objects ─────────────────────────────────────────────
        cur.execute(
            """
            INSERT INTO image_objects (id, image_id, label, confidence, bbox, rel_bbox)
            SELECT gen_random_uuid(), m.new_id, o.label, o.confidence, o.bbox, o.rel_bbox
            FROM image_objects o
            JOIN _image_map m ON o.image_id = m.old_id
            """
        )
        print(f"  image_objects: {cur.rowcount} rows inserted")

        # ── 8. Copy image_ocr ─────────────────────────────────────────────────
        cur.execute(
            """
            INSERT INTO image_ocr (id, image_id, text, confidence, box_2d, polygon)
            SELECT gen_random_uuid(), m.new_id, o.text, o.confidence, o.box_2d, o.polygon
            FROM image_ocr o
            JOIN _image_map m ON o.image_id = m.old_id
            """
        )
        print(f"  image_ocr: {cur.rowcount} rows inserted")

        # ── 9. Copy image_people (cluster_id → NULL, clusters are device-specific)
        cur.execute(
            """
            INSERT INTO image_people (
                id, image_id, label, confidence, bbox, rel_bbox, embedding, embedding_created_at
            )
            SELECT
                gen_random_uuid(), m.new_id,
                p.label, p.confidence, p.bbox, p.rel_bbox, p.embedding, p.embedding_created_at
            FROM image_people p
            JOIN _image_map m ON p.image_id = m.old_id
            """
        )
        print(f"  image_people: {cur.rowcount} rows inserted")

        # ── 10. Copy annotations ──────────────────────────────────────────────
        cur.execute(
            """
            INSERT INTO annotations (id, image_id, anno_type, points, label, timestamp, author)
            SELECT gen_random_uuid(), m.new_id, a.anno_type, a.points, a.label, a.timestamp, a.author
            FROM annotations a
            JOIN _image_map m ON a.image_id = m.old_id
            """
        )
        print(f"  annotations: {cur.rowcount} rows inserted")

        conn.commit()
        print("\nDB committed. Copying files …")

        copy_files(file_paths)
        print("Done.")

    except Exception as e:
        conn.rollback()
        print(f"\nERROR — rolled back: {e}", file=sys.stderr)
        raise
    finally:
        cur.close()
        conn.close()


if __name__ == "__main__":
    run()

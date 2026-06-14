"""
backfill_image_timezone.py
--------------------------
Recompute each Image's timezone + local wall-clock fields (local_timestamp,
year/month/day/hour, seconds_from_midnight, date) from the GPS-derived
ImageGPS.timezone.

Fixes images ingested while the camera's system timezone was stale: the captured
filename carried the wrong local wall time + %z offset, so Image.timestamp (UTC)
came out correct (offset and wall time cancel on parse), but the derived local
fields were wrong, and the live GPS pipeline used to skip overwriting an
already-set Image.timezone. ImageGPS.timezone already holds the correct
GPS-derived zone, so we re-derive the Image local fields from it.

Idempotent: images already correct are rewritten to the same values.

Usage:
    python backfill_image_timezone.py --dry-run        # count, do nothing
    python backfill_image_timezone.py --limit 100      # first 100 (test)
    python backfill_image_timezone.py                  # all
"""

import argparse
import logging
import os

from dotenv import load_dotenv
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

load_dotenv()
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger("backfill_image_timezone")

from database.models import Image, ImageGPS  # noqa: E402
from location.gps_pipeline import _apply_timezone_to_images  # noqa: E402


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--limit", type=int, default=None, help="process only first N images")
    args = ap.parse_args()

    engine = create_engine(os.environ["PG_URI"])
    Session = sessionmaker(bind=engine)

    with Session() as session:
        q = (
            select(Image.id, ImageGPS.timezone)
            .join(ImageGPS, ImageGPS.image_id == Image.id)
            .where(ImageGPS.timezone.isnot(None))
        )
        if args.limit:
            q = q.limit(args.limit)
        rows = session.execute(q).all()

    tz_by_image_id = {
        r.id: str(r.timezone)
        for r in rows
        if str(r.timezone) not in ("None", "nan", "")
    }
    logger.info("Images with a GPS timezone to backfill: %d", len(tz_by_image_id))
    if args.dry_run:
        return

    items = list(tz_by_image_id.items())
    BATCH = 500
    done = 0
    for i in range(0, len(items), BATCH):
        chunk = dict(items[i:i + BATCH])
        with Session() as session:
            _apply_timezone_to_images(session, chunk)
            session.commit()
        done += len(chunk)
        logger.info("Progress: %d/%d", done, len(items))

    logger.info("Done. Backfilled %d images.", done)


if __name__ == "__main__":
    main()

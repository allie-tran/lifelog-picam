"""One-off: run segmentation for cathal + LSC, no LLM annotations.

Iterates every (device, date) and calls load_all_segments(skip_annotations=True),
so no describe_segment_task is enqueued and no DaySummaryRecord is flagged.
"""
from dotenv import load_dotenv

load_dotenv()

import logging
import sys

from sqlalchemy import select

from database import SessionLocal
from database.models import Image
from services.segmentation import load_all_segments

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger("seg_run")

DEVICES = ["cathal", "LSC"]


def dates_for(session, device):
    rows = session.execute(
        select(Image.date)
        .where(Image.device == device, Image.deleted == False)
        .distinct()
        .order_by(Image.date.asc())
    ).scalars().all()
    return [d for d in rows if d]


def main():
    session = SessionLocal()
    for device in DEVICES:
        dates = dates_for(session, device)
        logger.info("device=%s dates=%d", device, len(dates))
        for i, date in enumerate(dates, 1):
            logger.info("[%s %d/%d] segmenting %s", device, i, len(dates), date)
            try:
                load_all_segments(session, device, date, skip_annotations=True)
            except Exception:
                logger.exception("FAILED device=%s date=%s", device, date)
                session.rollback()
    logger.info("done")


if __name__ == "__main__":
    main()

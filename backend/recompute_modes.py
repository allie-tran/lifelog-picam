"""
recompute_modes.py
------------------
Clear stored ImageGPS.mode and recompute it under the GPS-authoritative fusion
(CLIP confirm-only). Mode is the only thing rewritten — geocoding and segment
annotation are skipped (run_pipeline(modes_only=True)).

Usage:
    python recompute_modes.py --dry-run         # show GPS day count, do nothing
    python recompute_modes.py --limit 2         # clear+recompute 2 days (test)
    python recompute_modes.py                    # all GPS days
"""

import argparse
import logging
import os

from dotenv import load_dotenv
from sqlalchemy import create_engine, func, select, text
from sqlalchemy.orm import sessionmaker

load_dotenv()
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger("recompute_modes")

from database.models import Device, RawGPS  # noqa: E402
from location.gps_pipeline import run_pipeline  # noqa: E402


def gps_days(session) -> list[tuple[str, str]]:
    """
    (device, date) pairs that have RAW GPS — the only days run_pipeline can
    rebuild. Days imported straight into image_gps (e.g. the LSC'19 set) have no
    raw_gps and are skipped: they can't be reprocessed this way.
    """
    day = func.date(RawGPS.timestamp)
    rows = session.execute(
        select(Device.device_id, day)
        .join(Device, Device.id == RawGPS.device_id)
        .distinct()
        .order_by(day)
    ).all()
    return [(d, dt.strftime("%Y-%m-%d")) for d, dt in rows]


def clear_modes(session, days: list[tuple[str, str]]) -> int:
    """NULL out ImageGPS.mode for the given days (else COALESCE keeps old value)."""
    total = 0
    for device, date in days:
        res = session.execute(
            text("""
                UPDATE image_gps g SET mode = NULL
                FROM images i
                WHERE g.image_id = i.id AND i.device = :device AND i.date = :date
                  AND g.mode IS NOT NULL
            """),
            {"device": device, "date": date},
        )
        total += res.rowcount or 0
    session.commit()
    return total


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--limit", type=int, default=None, help="process only first N days")
    args = ap.parse_args()

    engine = create_engine(os.environ["PG_URI"])
    Session = sessionmaker(bind=engine)
    with Session() as session:
        days = gps_days(session)
    if args.limit:
        days = days[: args.limit]
    logger.info("GPS days to process: %d", len(days))
    if args.dry_run:
        return

    with Session() as session:
        cleared = clear_modes(session, days)
    logger.info("Cleared mode on %d image_gps rows", cleared)

    ok, failed = 0, 0
    for idx, (device, date) in enumerate(days, 1):
        with Session() as session:
            try:
                run_pipeline(session, device, date, modes_only=True)
                ok += 1
            except Exception:
                session.rollback()
                failed += 1
                logger.exception("Failed device=%s date=%s", device, date)
        if idx % 25 == 0:
            logger.info("Progress: %d/%d (ok=%d failed=%d)", idx, len(days), ok, failed)

    logger.info("Done. %d days ok, %d failed.", ok, failed)


if __name__ == "__main__":
    main()

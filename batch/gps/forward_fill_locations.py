"""
forwardfill_location_id.py — forward-fill images.location_id within each day.

Loads only images where location_id IS NULL alongside all images that have
a location_id (needed as fill sources), forward-fills within each calendar
day, marks filled rows with location_interpolated=True, then writes only
the changed rows back via pandas + SQLAlchemy.

Usage:
    python forwardfill_location_id.py
    python forwardfill_location_id.py --dry-run

Requirements:
    pip install sqlalchemy psycopg2-binary pandas tqdm
"""

import argparse
import uuid

import pandas as pd
from sqlalchemy import create_engine, text
from sqlalchemy import UUID, Boolean
from tqdm.auto import tqdm
from datetime import datetime, timezone

# ─── Config ───────────────────────────────────────────────────────────────────

DATABASE_URL = "postgresql+psycopg://postgres:lsc26@localhost/lifelog-picam"
DEVICE = "cathal"
START_DATE = "2020-07-01"

# ─── Load ─────────────────────────────────────────────────────────────────────


def load_images(engine) -> pd.DataFrame:
    """
    Load all images for DEVICE since START_DATE.
    We need rows with location_id too — they act as fill sources.
    Only id, timestamp, date, location_id, and location_interpolated are needed.
    """
    start_time = datetime.fromisoformat(START_DATE)
    return pd.read_sql(
        text(
            """
            SELECT id,
                   timestamp,
                   date,
                   location_id,
                   location_interpolated
            FROM   images
            WHERE  device    = :device
              AND  timestamp >= :start_time
            ORDER  BY timestamp
        """
        ),
        engine,
        params={"device": DEVICE, "start_time": start_time},
    )


# ─── Forward-fill ─────────────────────────────────────────────────────────────


def forwardfill(df: pd.DataFrame) -> pd.DataFrame:
    """
    Within each calendar day:
      - Forward-fill location_id from the most recent non-null value.
      - Backfill any leading NULLs from the day's first known location_id.
      - Mark rows that were NULL and received a value as location_interpolated=True.

    Returns only the rows that changed (were NULL and got filled).
    """
    # Track which rows started as NULL
    originally_null = df["location_id"].isna()

    # Forward-fill then backfill within each day
    df["location_id"] = df.groupby("date")["location_id"].transform(
        lambda s: s.ffill().bfill()
    )

    # Rows that were NULL and now have a value
    filled_mask = originally_null & df["location_id"].notna()
    df.loc[filled_mask, "location_interpolated"] = True

    return df[filled_mask].copy()


# ─── Write back ───────────────────────────────────────────────────────────────


def write_back(filled: pd.DataFrame, engine, dry_run: bool) -> None:
    """
    Update location_id and location_interpolated for each filled row.
    Uses a temp table + UPDATE FROM for efficiency rather than row-by-row.
    """
    if filled.empty:
        print("  No rows to write back.")
        return

    updates = filled[["id", "location_id", "location_interpolated"]].copy()

    if dry_run:
        print(f"  [DRY RUN] would update {len(updates)} rows")
        print(updates.head(10).to_string(index=False))
        return

    with engine.begin() as conn:
        # Write to a temp table
        updates.to_sql(
            "_ff_updates",
            conn,
            if_exists="replace",
            index=False,
            dtype={"id": UUID, "location_id": UUID, "location_interpolated": Boolean},
        )

        result = conn.execute(
            text(
                """
            UPDATE images
            SET    location_id           = u.location_id,
                   location_interpolated = u.location_interpolated
            FROM   _ff_updates u
            WHERE  images.id = u.id::uuid
        """
            )
        )

        conn.execute(text("DROP TABLE IF EXISTS _ff_updates"))

    print(f"  Updated {result.rowcount} rows")


# ─── Main ────────────────────────────────────────────────────────────────────


def run(db_url: str, dry_run: bool) -> None:
    engine = create_engine(db_url)

    print("Loading images…")
    df = load_images(engine)
    print(
        f"  {len(df)} images loaded  ({df['location_id'].isna().sum()} without location_id)"
    )

    if df["location_id"].isna().sum() == 0:
        print("Nothing to fill.")
        return

    print("Forward-filling by day…")
    filled = forwardfill(df)

    days_affected = filled["date"].nunique()
    print(f"  {len(filled)} rows filled across {days_affected} days")

    still_null = df["location_id"].isna().sum()
    if still_null:
        print(f"  {still_null} rows still NULL (days with no located image at all)")
        print("Days:", df[df["location_id"].isna()]["date"].unique())

    print("Writing back…" if not dry_run else "Dry run — skipping write.")
    write_back(filled, engine, dry_run)

    print("\n─── Summary ─────────────────────────────────────────────")
    print(f"  Rows filled        : {len(filled)}")
    print(f"  Days affected      : {days_affected}")
    print(f"  Rows still NULL    : {still_null}")
    if dry_run:
        print("  (dry run — no writes committed)")


# ─── CLI ─────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Forward-fill images.location_id within each calendar day."
    )
    parser.add_argument("--db", default=DATABASE_URL, help="SQLAlchemy database URL")
    parser.add_argument(
        "--dry-run", action="store_true", help="Show what would change but do not write"
    )
    args = parser.parse_args()

    run(db_url=args.db, dry_run=args.dry_run)

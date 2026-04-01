"""
populate_locations.py — enrich picam.images with a `location` field.

For each stop segment in semantic_stops.csv that has an fsq_id:
  1. Fetch place details from the Foursquare API
  2. Build a location dict
  3. Update all images whose timestamp falls within [start_ts, end_ts]

Skips move segments and stops without an fsq_id.

Usage:
    python populate_locations.py
    python populate_locations.py --segments path/to/semantic_stops.csv --dry-run

Requirements:
    pip install pymongo requests
    export FSQ_API_KEY=your_key_here
"""

import argparse
import bisect
import csv
import json
import os
import sys
import time
from pprint import pprint

import requests
from pymongo import MongoClient, UpdateOne

# ─── Config ───────────────────────────────────────────────────────────────────


SEGMENTS_FILE = "files/nominatim_semantic_stops.csv"
_names = [field_name for field_name in field_names if field_name]

PG_URI = "postgresql+psycopg://postgres:lsc26@localhost/lifelog-picam"
engine = create_engine(PG_URI)
session = Session(bind=engine.connect())


# ─── CSV loading ──────────────────────────────────────────────────────────────
import pandas as pd


def load_stop_segments(csv_path: str) -> list[dict]:
    """Return only stop rows that have an fsq_id."""
    stops = []
    df = pd.read_csv(csv_path, dtype=str, sep=";")
    df.fillna("", inplace=True)
    for _, row in df.iterrows():
        if str(row.get("label")) != "1":
            continue
        stops.append(
            {
                "start_ts": float(row["start_ts"]),
                "end_ts": float(row["end_ts"]),
                "fsq_id": row.get("fsq_place_id", "").strip(),
                "name": row.get("name", "").strip(),
                "region": row.get("location", "").strip(),
                "stop": row.get("label", "0") == "1",
                "info": row.get("categories", "").strip(),
                "country": row.get("country", "").strip(),
                "city": row.get("city", "").strip(),
                "region": row.get("region", []).strip(),
                "address": row.get("address", "").strip(),
                "timezone": row.get("timezone", "").strip(),
            }
        )
    return stops


# ─── Segment index for fast timestamp lookup ──────────────────────────────────


class SegmentIndex:
    """
    Given a timestamp, return the best matching segment:
      - The segment whose [start_ts, end_ts] contains the timestamp, or
      - The closest segment by endpoint distance if the timestamp is in a gap.
    """

    def __init__(self, segments: list[dict]):
        self.segs = segments
        self.start_ts = [s["start_ts"] for s in segments]

    def find(self, ts: float) -> dict | None:
        if not self.segs:
            return None

        # Rightmost segment that starts at or before ts
        idx = bisect.bisect_right(self.start_ts, ts) - 1

        # Direct hit: ts falls inside this segment's window
        if idx >= 0 and ts <= self.segs[idx]["end_ts"]:
            return self.segs[idx]

        # ts is in a gap — compare distance to neighbouring endpoints
        candidates = []
        if idx >= 0:
            candidates.append((abs(ts - self.segs[idx]["end_ts"]), self.segs[idx]))
        if idx + 1 < len(self.segs):
            candidates.append(
                (abs(ts - self.segs[idx + 1]["start_ts"]), self.segs[idx + 1])
            )

        if not candidates:
            return self.segs[0]

        return min(candidates, key=lambda x: x[0])[1]


# ─── MongoDB update ───────────────────────────────────────────────────────────
from datetime import datetime

start_date = "2020-07-01"
start_timestamp = datetime.fromisoformat(start_date, tzinfo=datetime.timezone.utc)
BASE_QUERY = {"device": "cathal", "timestamp": {"$gte": start_timestamp * 1000}}


def build_bulk_ops(col, segment: dict, dry_run: bool) -> tuple[int, int]:
    """
    Return (matched, ops_count) for images in [start_ts, end_ts].
    In dry_run mode, only counts — does not write.
    """
    query = {
        **BASE_QUERY,
        "$or": [
            {
                "timestamp": {
                    "$gte": segment["start_ts"] * 1000,
                    "$lte": segment["end_ts"] * 1000,
                }
            },
            {
                "gps.timestamp": {
                    "$gte": segment["start_ts"],
                    "$lte": segment["end_ts"],
                }
            },
        ],
    }

    if dry_run:
        count = col.count_documents(query)
        if count == 0:
            print(query)
        return count, 0

    result = col.update_many(
        query,
        {"$set": {"location": segment}},
    )
    return result.matched_count, result.modified_count


def fetch_unenriched(col, run_id) -> list[dict]:
    """Pass 2: images that still have no location field."""
    return list(
        col.find(
            {
                **BASE_QUERY,
                "$or": [
                    {"location": {"$exists": False}},
                    {"location": None},
                    {"location.run_id": {"$ne": run_id}},
                ],
            },
            {"_id": 1, "timestamp": 1},
            sort=[("timestamp", 1)],
        )
    )


# ─── Main ────────────────────────────────────────────────────────────────────
from tqdm.auto import tqdm


def run(segments_file: str, mongo_uri: str, dry_run: bool):
    print(f"Loading segments from {segments_file}…")
    segments = load_stop_segments(segments_file)
    print(f"  {len(segments)} stop segments with fsq_id")

    if not segments:
        print("Nothing to do.")
        return

    client = MongoClient(mongo_uri)
    col = client[DB][COL_IMAGES]

    total_matched = 0
    total_modified = 0
    fsq_errors = 0

    run_id = int(time.time())

    # To account for gaps, make the end_ts expand to the next segment's start_ts
    for i, seg in enumerate(segments):
        if i + 1 < len(segments):
            seg["end_ts"] = segments[i + 1]["start_ts"]

    for i, seg in tqdm(
        enumerate(segments, 1), total=len(segments), desc="Processing segments"
    ):
        seg["run_id"] = run_id
        matched, modified = build_bulk_ops(col, seg, dry_run)
        if dry_run:
            print(f"[DRY RUN] would update {matched} images")

        total_matched += matched
        total_modified += modified

    print()
    print("─── Summary ─────────────────────────────────────────────")
    print(f"  Segments processed : {len(segments)}")
    print(f"  FSQ errors         : {fsq_errors}")
    print(f"  Images matched     : {total_matched}")
    if not dry_run:
        print(f"  Images modified    : {total_modified}")
    else:
        print("  (dry run — no writes)")

    print("\nFallback for images outside stop windows…")

    unenriched = fetch_unenriched(col, run_id)
    print(f"  {len(unenriched)} images without location")
    if not unenriched:
        print("  Nothing to do.")
        return 0, 0

    index = SegmentIndex(segments)
    total_matched = total_modified = 0
    no_match = 0
    for img in tqdm(unenriched, desc="Assigning fallback segments"):

        # Get the previous valid location

        ts = img["timestamp"] / 1000  # collection stores ms
        seg = index.find(ts)
        if seg is None:
            print(f"  WARNING: no segment found for ts={ts:.0f}, skipping")
            no_match += 1
            continue

        ok = (
            col.update_one(
                {"_id": img["_id"]}, {"$set": {"location": seg}}
            ).modified_count
            == 1
        )
        total_matched += 1
        total_modified += int(ok and not dry_run)

    print(
        f"  ── Pass 2 done  matched={total_matched}"
        + (f"  modified={total_modified}" if not dry_run else "  [DRY]")
        + (f"  no_match={no_match}" if no_match else "")
    )

    client.close()


# ─── CLI ─────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Populate picam.images with a location field from Foursquare."
    )
    parser.add_argument(
        "--segments",
        default=SEGMENTS_FILE,
        help=f"Segments CSV (default: {SEGMENTS_FILE})",
    )
    parser.add_argument(
        "--mongo", default=MONGO_URI, help=f"MongoDB URI (default: {MONGO_URI})"
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Count matching images but do not write to MongoDB",
    )
    args = parser.parse_args()

    run(
        segments_file=args.segments,
        mongo_uri=args.mongo,
        dry_run=args.dry_run,
    )

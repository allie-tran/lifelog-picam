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

import os
import ast
from collections import defaultdict
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

import pandas as pd
from dotenv import load_dotenv
from sqlalchemy import create_engine, select, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session
from timezonefinder import TimezoneFinder

from models import Image, ImageGPS, Location

# ─── Confeg ───────────────────────────────────────────────────────────────────

SEGMENTS_FILE = "files/nominatim_semantic_stops.csv"
GPS_FILE = "files/image_gps.csv"
OLD_GPS = "files/lsc24_images.csv"
DEVICE_ID = "cathal"
CHUNK = 1000

load_dotenv()
PG_URI = os.getenv("PG_URI", "postgresql://postgres:password@localhost:5432/lsc24")
engine = create_engine(PG_URI)

# ─── Main ────────────────────────────────────────────────────────────────────
from tqdm.auto import tqdm


def create_key(fsq_place_id, name, country, address, is_stop, info):
    if fsq_place_id and fsq_place_id != "None":
        key = f"fsq_id={fsq_place_id}"
    else:
        key = f"{name}, {country}, {address}, {info}"
    key = f"stop={is_stop == 1}, {key}"
    return key


tf = TimezoneFinder()
timezone_cache = {}


def cached_find_timezone(lat, lon):
    if (lat, lon) in timezone_cache:
        return timezone_cache[(lat, lon)]
    tz = tf.timezone_at(lng=lon, lat=lat)
    timezone_cache[(lat, lon)] = tz
    return tz

def safe_parse(val):
    if pd.isna(val) or val == "":
        return []
    try:
        # literal_eval handles single/double quote mismatches better than JSON
        return ast.literal_eval(val)
    except (ValueError, SyntaxError):
        # If it still fails, fix the double-quote "King"s" issue manually
        fixed_val = val.replace('"s ', "'s ")
        try:
            return ast.literal_eval(fixed_val)
        except:
            return []

def add_null_address(loc):
    if loc["address"] == "":
        region = loc.get("region", "")
        if "[" in region:
            region = safe_parse(region)
        else:
            region = [region] if region else []
        loc["address"] = ", ".join(region) if region else loc["country"]
    return loc["address"]

def run_segments():
    print(
        f"Loading segments from {SEGMENTS_FILE} and image GPS data from {GPS_FILE}..."
    )
    segments = pd.read_csv(SEGMENTS_FILE, sep=";")
    segments = segments.fillna("")
    segments["address"] = segments.apply(add_null_address, axis=1)
    image_gps = pd.read_csv(GPS_FILE)

    # set segment_id as index
    image_gps.set_index("segment_id", inplace=True)
    segments["key"] = segments.apply(
        lambda row: create_key(
            row["fsq_place_id"],
            row["name"],
            row["country"],
            row["address"],
            row["is_stop"],
            row["categories"],
        ),
        axis=1,
    )

    all_places = defaultdict(list)
    for _, seg in segments.iterrows():
        all_places[seg["key"]].append(seg)

    old_gps = pd.read_csv(OLD_GPS, sep=";")
    old_gps = old_gps.fillna("")
    old_gps["address"] = old_gps.apply(add_null_address, axis=1)
    old_gps["key"] = old_gps.apply(
        lambda row: create_key(
            row["fsq_place_id"],
            row["name"],
            row["country"],
            row["address"],
            row["is_stop"],
            row["categories"],
        ),
        axis=1,
    )
    for _, row in old_gps.iterrows():
        row["segment_id"] = -1
        all_places[row["key"]].append(row)

    with Session(engine) as session:
        for key in tqdm(all_places, desc="Inserting locations"):
            first_place = all_places[key][0]
            all_segment_ids = set(seg["segment_id"] for seg in all_places[key])
            images_to_update = image_gps[
                image_gps.index.isin(all_segment_ids)
            ].image_path.tolist()
            # add old image_path in old_gps that match the key
            old_images = old_gps[old_gps["key"] == key].image_path.tolist()
            images_to_update += old_images

            stmt = insert(Location).values(
                key=key,
                name=first_place["name"],
                country=first_place["country"],
                fsq_id=first_place["fsq_place_id"],
                info=first_place["categories"],
                stop=first_place["is_stop"] == 1,
                timezone=first_place["timezone"],
                address=first_place["address"],
            )

            stmt = stmt.on_conflict_do_update(
                index_elements=["key"],
                set_={
                    "key": stmt.excluded.key,
                },
            ).returning(Location.id)

            try:
                row_id = session.execute(stmt).scalar()
                session.commit()
            except SQLAlchemyError as e:
                error = str(e.__dict__.get("orig"))
                print(f"Error inserting/updating location for {key}: {error}")
                session.rollback()
                # If it failed here, it's likely the name/address constraint triggered instead
                # We fetch the existing record to get the ID
                existing = (
                    session.query(Location)
                    .filter(
                        Location.key == key,
                        Location.name == first_place["name"],
                        Location.country == first_place["country"],
                        Location.address == first_place["address"],
                        Location.stop == (first_place["is_stop"] == 1),
                        Location.fsq_id == first_place["fsq_place_id"],
                    )
                    .first()
                )

                print(
                    f"Conflict detected for {key}. Fetched existing location with ID: {existing.id if existing else 'None'}"
                )
                row_id = existing.id if existing else None

            if row_id is not None and len(images_to_update) > 0:
                batch_size = 10000
                for i in range(0, len(images_to_update), batch_size):
                    try:
                        session.execute(
                            update(Image)
                            .where(
                                Image.image_path.in_(
                                    images_to_update[i : i + batch_size]
                                )
                            )
                            .values(location_id=row_id)
                        )
                    except SQLAlchemyError as e:
                        error = str(e.__dict__.get("orig"))
                        print(
                            f"Error updating images for location id {row_id}: {error}"
                        )

                session.commit()


def run_gps() -> None:
    image_gps = pd.read_csv(GPS_FILE)
    old_gps = pd.read_csv(OLD_GPS, sep=";")
    old_gps["elevation"] = 0.0
    old_gps["interpolated"] = True
    image_gps = pd.concat([image_gps, old_gps], ignore_index=True)

    # Step 1: Bulk resolve image_path -> image_id in one query
    paths = image_gps["image_path"].tolist()

    path_to_id: dict[str, int] = {}
    with Session(engine) as session:
        for i in range(0, len(paths), CHUNK):
            chunk = paths[i : i + CHUNK]
            rows = session.execute(
                select(Image.image_path, Image.id).where(
                    Image.image_path.in_(chunk),
                    Image.device == DEVICE_ID,
                )
            ).all()
            path_to_id.update({r.image_path: r.id for r in rows})

    # Step 2: Build rows, resolve timezone
    records: list[dict] = []
    for _, row in tqdm(
        image_gps.iterrows(), total=len(image_gps), desc="Building GPS records"
    ):
        image_id = path_to_id.get(row.image_path)
        if image_id is None:
            continue  # image not in DB yet, skip
        tz = cached_find_timezone(round(row.latitude, 4), round(row.longitude, 4))
        records.append(
            {
                "image_id": image_id,
                "latitude": row.latitude,
                "longitude": row.longitude,
                "elevation": row.elevation,
                "interpolated": row.interpolated,
                "timezone": tz,
            }
        )

    # Step 3: Bulk upsert in chunks
    with Session(engine) as session:
        for i in tqdm(range(0, len(records), CHUNK), desc="Upserting GPS data"):
            chunk = records[i : i + CHUNK]
            stmt = insert(ImageGPS).values(chunk)
            stmt = stmt.on_conflict_do_update(
                index_elements=["image_id"],
                set_={
                    "latitude": stmt.excluded.latitude,
                    "longitude": stmt.excluded.longitude,
                    "elevation": stmt.excluded.elevation,
                    "interpolated": stmt.excluded.interpolated,
                    "timezone": stmt.excluded.timezone,
                },
            )
            try:
                session.execute(stmt)
                session.commit()
            except SQLAlchemyError as e:
                print(f"Error upserting GPS chunk: {e.__dict__.get('orig')}")
                session.rollback()


def update_localtime():
    df = pd.read_csv(GPS_FILE)
    old_gps = pd.read_csv(OLD_GPS, sep=";")
    df = pd.concat([df, old_gps], ignore_index=True)

    # df = df[df["image_path"].str.startswith(f"2022-10-16")]
    with Session(engine) as session:
        results = []
        for i in tqdm(range(0, len(df), CHUNK), desc="Fetching image metadata"):
            chunk = df.iloc[i : i + CHUNK]["image_path"].tolist()
            results += session.execute(
                select(Image.id, Image.image_path, ImageGPS.timezone)
                .join(ImageGPS, ImageGPS.image_id == Image.id)
                .where(
                    Image.image_path.in_(chunk),
                    Image.device == DEVICE_ID,
                )
            ).all()

    path_to_meta: dict[str, tuple[int, str]] = {
        r.image_path: (r.id, r.timezone) for r in results
    }

    # To postgres
    with Session(engine) as session:
        for i in tqdm(range(0, len(df), CHUNK), desc="Updating timestamps"):
            chunk = df.iloc[i : i + CHUNK]
            rows = []
            for _, row in chunk.iterrows():
                meta = path_to_meta.get(row["image_path"])
                if meta is None:
                    continue
                image_id, tz_name = meta
                tz = ZoneInfo(tz_name) if tz_name else ZoneInfo("UTC")
                ts = datetime.strptime(
                    row["image_path"].split("/")[-1].split(".")[0], "%Y%m%d_%H%M%S"
                )
                local_dt = ts.replace(tzinfo=timezone.utc).astimezone(tz)
                date = ts.strftime("%Y-%m-%d")
                if date == "2022-10-16":
                    print(
                        f"Image {row['image_path']} has timestamp {ts} and timezone {tz_name}, local time {local_dt}"
                    )
                rows.append(
                    {
                        "id": image_id,
                        "timestamp": ts,
                        "local_timestamp": local_dt,
                        "timezone": tz_name,
                        "year": local_dt.year,
                        "month": local_dt.month,
                        "day": local_dt.day,
                        "date": ts.strftime("%Y-%m-%d"),
                        "hour": local_dt.hour,
                    }
                )

            if not rows:
                continue

            session.execute(
                update(Image).execution_options(synchronize_session=None),
                rows,
            )
            session.commit()


if __name__ == "__main__":
    run_segments()
    # run_gps()
    # update_localtime()

import bisect
import os
import random
from datetime import datetime, timedelta, timezone
from typing import Counter
import pandas as pd

import gpxpy
from gpxpy.gpx import GPX_10_POINT_FIELDS
from pymongo import MongoClient
from sqlalchemy import create_engine, insert, select, text
from sqlalchemy.orm import Session
from tqdm import tqdm

from models import Base, Image, ImageGPS

FOLDER = "GPS"
fields = GPX_10_POINT_FIELDS
field_names = [field.name for field in fields]
field_names = [field_name for field_name in field_names if field_name]

PG_URI = "postgresql+psycopg://postgres:lsc26@localhost/lifelog-picam"
engine = create_engine(PG_URI)
session = Session(bind=engine.connect())


# Parse the GPS data and add it to the database
def parse_gps(date, gps_file):
    try:
        gpx_file = open(gps_file, "r")
        gpx = gpxpy.parse(gpx_file)
    except Exception as e:
        print(f"Error parsing {gps_file}: {e}")
        return

    # Align time, with gps data
    points = []
    for track in gpx.tracks:
        for segment in track.segments:
            for point in segment.points:
                entry = {name: getattr(point, name) for name in field_names}
                point.time = point.time.astimezone(timezone.utc).replace(tzinfo=None)
                entry["timestamp"] = point.time
                entry["elevation"] = point.elevation or 0.0
                entry["formatted_time"] = point.time.strftime("%Y%m%d_%H%M%S")
                entry["interpolated"] = False
                points.append(entry)
    return points


def assign_gps_to_images(date, points, point_timestamps):

    # Assign GPS data to images
    images = session.execute(
        select(Image.id, Image.timestamp).where(
            Image.device == "cathal",
            Image.date == date,
        )
    ).fetchall()

    images = list(images)
    if len(images) == 0:
        return  # No images for this date, skip processing
    print(f"Processing {len(images)} images and {len(points)} GPS points for {date}")

    stats = Counter()
    gaps = []  # track actual time deltas for distribution insight

    rows = []

    for image in images:
        img_ts = image.timestamp

        # Find insertion point
        j = bisect.bisect_left(point_timestamps, img_ts)

        # Get candidates either side
        candidates = []
        if j < len(points):
            candidates.append(points[j])
        if j > 0:
            candidates.append(points[j - 1])

        if not candidates:
            stats["no_gps_data"] += 1
            continue  # No GPS data at all

        closest = min(candidates, key=lambda p: abs(p["timestamp"] - img_ts))
        closest = closest.copy()  # avoid mutating original point
        gap_s = abs(closest["timestamp"] - img_ts)
        gaps.append(gap_s)

        if gap_s <= timedelta(seconds=30):
            stats["within_30s"] += 1
        elif gap_s <= timedelta(seconds=60):
            stats["within_60s"] += 1
        else:
            stats["gap_too_large"] += 1
            # interpolation could be done here
            left = points[j - 1] if j > 0 else None
            right = points[j] if j < len(points) else None
            if left and right:
                total_gap = (right["timestamp"] - left["timestamp"]).total_seconds()
                if total_gap > 0:
                    img_gap = (img_ts - left["timestamp"]).total_seconds()
                    ratio = img_gap / total_gap
                    closest = {
                        "latitude": left["latitude"]
                        + ratio * (right["latitude"] - left["latitude"]),
                        "longitude": left["longitude"]
                        + ratio * (right["longitude"] - left["longitude"]),
                        "elevation": left["elevation"]
                        + ratio * (right["elevation"] - left["elevation"]),
                        "timestamp": img_ts,
                        "date": date,
                        "interpolated": True,
                    }
                else:
                    closest = {
                        "latitude": left["latitude"],
                        "longitude": left["longitude"],
                        "elevation": left["elevation"],
                        "timestamp": img_ts,
                        "interpolated": True,
                    }
            elif left:
                closest = {
                    "latitude": left["latitude"],
                    "longitude": left["longitude"],
                    "elevation": left["elevation"],
                    "timestamp": img_ts,
                    "interpolated": True,
                }
            elif right:
                closest = {
                    "latitude": right["latitude"],
                    "longitude": right["longitude"],
                    "elevation": right["elevation"],
                    "timestamp": img_ts,
                    "interpolated": True,
                }

        closest["timestamp"] = (
            closest["timestamp"].replace(tzinfo=timezone.utc).timestamp()
        )
        closest["image_id"] = image.id
        closest["gaps_s"] = gap_s.total_seconds()
        closest["formatted_time"] = datetime.utcfromtimestamp(
            closest["timestamp"]
        ).strftime("%Y%m%d_%H%M%S")
        closest["date"] = date
        rows.append(closest)

    session.execute(insert(ImageGPS), rows)
    session.commit()
    return points


if __name__ == "__main__":
    # # Drop and recreate the ImageGPS table to start fresh
    # session.execute(text("DROP TABLE IF EXISTS image_gps"))

    # create table first
    Base.metadata.create_all(engine)
    csv_file = "all_gps_points.csv"
    if os.path.exists(csv_file):
        df = pd.read_csv(csv_file)
        dates = sorted(set(df["date"]))
        all_points = df.to_dict(orient="records")
    else:
        files = os.listdir(FOLDER)
        all_points = []
        dates = []
        for file in files:
            if file.endswith(".gpx"):
                gps_file = os.path.join(FOLDER, file)
                if "(" in file:
                    date = datetime.strptime(file.split("(")[0].strip(), "%Y%m%d")
                else:
                    date = datetime.strptime(file.split(".")[0], "%Y%m%d")
                month = date.month
                date = datetime.strftime(date, "%Y-%m-%d")
                dates.append(date)
                new_points = parse_gps(date, gps_file)
                if new_points:
                    all_points.extend(new_points)

        all_points = sorted(all_points, key=lambda p: p["timestamp"])
        df = pd.DataFrame(all_points)
        df.to_csv("all_gps_points.csv", index=False)

    point_timestamps = [p["timestamp"] for p in all_points]

    dates = sorted(set(dates))
    for date in tqdm(dates):
        assign_gps_to_images(date, all_points, point_timestamps)

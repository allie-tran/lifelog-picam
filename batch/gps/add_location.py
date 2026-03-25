import bisect
import os
import random
from datetime import datetime, timezone
from typing import Counter

import gpxpy
from gpxpy.gpx import GPX_10_POINT_FIELDS
from numpy import select
from pymongo import MongoClient
from sqlalchemy import create_engine, insert

from models import Image, ImageGPS

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
                point.time = point.time.replace(tzinfo=timezone.utc)
                entry["timestamp"] = point.time
                entry["formatted_time"] = point.time.strftime("%Y%m%d_%H%M%S")
                entry["interpolated"] = False
                points.append(entry)

    points.sort(key=lambda p: p["timestamp"])
    point_timestamps = [p["timestamp"] for p in points]

    # Assign GPS data to images
    images = session.execute(
        select(Image.id, Image.timestamp).where(
            Image.device == "cathal",
            Image.timestamp >= points[0]["timestamp"],
            Image.timestamp <= points[-1]["timestamp"],
        )
    ).fetchall()

    images = list(images)
    if len(images) == 0:
        return  # No images for this date, skip processing
    print(f"Processing {len(images)} images and {len(points)} GPS points for {date}")
    MAX_GAP_MS = 60  # 1 minute

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
        gap_s = abs(closest["timestamp"] - img_ts)
        gaps.append(gap_s)

        if gap_s <= 30:
            stats["within_30s"] += 1
        elif gap_s <= 60:
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
                        "latitude": left["latitude"] + ratio * (right["latitude"] - left["latitude"]),
                        "longitude": left["longitude"] + ratio * (right["longitude"] - left["longitude"]),
                        "altitude": left["altitude"] + ratio * (right["altitude"] - left["altitude"]),
                        "timestamp": img_ts,
                        "interpolated": True,
                    }
                else:
                    closest = {
                        "latitude": left["latitude"],
                        "longitude": left["longitude"],
                        "altitude": left["altitude"],
                        "timestamp": img_ts,
                        "interpolated": True,
                    }
            elif left:
                closest = {
                    "latitude": left["latitude"],
                    "longitude": left["longitude"],
                    "altitude": left["altitude"],
                    "timestamp": img_ts,
                    "interpolated": True,
                }
            elif right:
                closest = {
                    "latitude": right["latitude"],
                    "longitude": right["longitude"],
                    "altitude": right["altitude"],
                    "timestamp": img_ts,
                    "interpolated": True,
                }

        rows.append(
            insert(ImageGPS).values(
                image_id=image.id,
                latitude=closest["latitude"],
                longitude=closest["longitude"],
                altitude=closest["altitude"],
                timestamp=closest["timestamp"],
                interpolated=closest.get("interpolated", False),
            )
        )

    total = len(images)
    print(f"Date:             {date}")
    print(f"Total images:     {total}")
    print(f"GPS points:       {len(points)}")
    print(
        f"  within 30s:     {stats['within_30s']} ({100*stats['within_30s']//total}%)"
    )
    print(
        f"  within 60s:     {stats['within_60s']} ({100*stats['within_60s']//total}%)"
    )
    print(
        f"  gap too large:  {stats['gap_too_large']} ({100*stats['gap_too_large']//total}%)"
    )
    print(
        f"  no gps data:    {stats['no_gps_data']} ({100*stats['no_gps_data']//total}%)"
    )
    if gaps:
        print(f"Median gap:       {sorted(gaps)[len(gaps)//2]:.2f}s")
        print(f"Max gap:          {max(gaps):.2f}s")
        print(f"Mean gap:         {sum(gaps)/len(gaps):.2f}s")

    return points


if __name__ == "__main__":
    files = os.listdir(FOLDER)
    all_points = []
    for file in files:
        if file.endswith(".gpx"):
            if file.startswith("202202"):
                gps_file = os.path.join(FOLDER, file)
                if "(" in file:
                    date = datetime.strptime(file.split("(")[0].strip(), "%Y%m%d")
                else:
                    date = datetime.strptime(file.split(".")[0], "%Y%m%d")
                month = date.month
                date = datetime.strftime(date, "%Y-%m-%d")
                new_points = parse_gps(date, gps_file)
                if new_points:
                    all_points.extend(new_points)

    # sort all points by timestamp and print overall stats
    all_points = sorted(all_points, key=lambda p: p["timestamp"])

    # export to CSV for analysis
    with open("gps_points.csv", "w") as f:
        f.write(",".join(field_names) + "\n")
        for point in all_points:
            f.write(",".join(str(point.get(name, "")) for name in field_names) + "\n")

    # After processing all dates, print overall stats
    total_images = session.execute(select(Image).where(Image.device == "cathal").count()).scalar()
    gps_count = session.execute(select(ImageGPS).join(Image).where(Image.device == "cathal").count()).scalar()
    print("\nOverall Stats:")
    print(f"Total images: {total_images}")
    print(f"Images with GPS: {gps_count} ({100*gps_count//total_images}%)")

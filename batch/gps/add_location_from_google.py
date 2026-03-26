import bisect
import os
import random
from datetime import datetime, timedelta, timezone
from typing import Counter
import pandas as pd
import json

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
            Image.device == "allie",
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
                        "latitude": left["latitude"] + ratio * (right["latitude"] - left["latitude"]),
                        "longitude": left["longitude"] + ratio * (right["longitude"] - left["longitude"]),
                        "elevation": left["elevation"] + ratio * (right["elevation"] - left["elevation"]),
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

        closest["timestamp"] = closest["timestamp"].replace(tzinfo=timezone.utc).timestamp()
        closest["image_id"] = image.id
        closest["gaps_s"] = gap_s.total_seconds()
        closest["formatted_time"] = datetime.utcfromtimestamp(closest["timestamp"]).strftime("%Y%m%d_%H%M%S")
        closest["date"] = date
        rows.append(closest)

    # gaps = [gap.total_seconds() for gap in gaps]
    # total = len(images)
    # print(f"Date:             {date}")
    # print(f"Total images:     {total}")
    # print(f"GPS points:       {len(points)}")
    # print(
    #     f"  within 30s:     {stats['within_30s']} ({100*stats['within_30s']//total}%)"
    # )
    # print(
    #     f"  within 60s:     {stats['within_60s']} ({100*stats['within_60s']//total}%)"
    # )
    # print(
    #     f"  gap too large:  {stats['gap_too_large']} ({100*stats['gap_too_large']//total}%)"
    # )
    # print(
    #     f"  no gps data:    {stats['no_gps_data']} ({100*stats['no_gps_data']//total}%)"
    # )
    # if gaps:
    #     print(f"Median gap:       {sorted(gaps)[len(gaps)//2]:.2f}s")
    #     print(f"Max gap:          {max(gaps):.2f}s")
    #     print(f"Mean gap:         {sum(gaps)/len(gaps):.2f}s")
    # print(rows[:2])  # print first 2 rows for sanity check
    # print(f"Inserted {len(rows)} GPS records for {date}\n")

    session.execute(insert(ImageGPS), rows)
    session.commit()
    return points


if __name__ == "__main__":
    # # Drop and recreate the ImageGPS table to start fresh
    # session.execute(text("DROP TABLE IF EXISTS image_gps"))

    # create table first
    Base.metadata.create_all(engine)
    json_file = "Timeline.json"
    with open(json_file, "r") as f:
        timeline = json.load(f)
        timeline = timeline["semanticSegments"]

    segments = []
    all_points = []
    dates = set()
    for entry in timeline:
        # we have startTime, endTime, timelinePath
        for point in entry.get("timelinePath", []):
            lat, lon = point["point"].split(",")
            # remove the degree symbol
            lat = lat.replace("°", "").strip()
            lon = lon.replace("°", "").strip()
            lat = float(lat)
            lon = float(lon)
            time = datetime.fromisoformat(point["time"]) # this has timezone info
            time = time.astimezone(timezone.utc).replace(tzinfo=None)
            all_points.append({
                "latitude": lat,
                "longitude": lon,
                "timestamp": time,
                "date": time.date().isoformat(),
                "interpolated": False,
            })
            dates.add(time.date().isoformat())

        if "visit" in entry:
            lat_lon = entry["visit"]["topCandidate"]["placeLocation"]["latLng"].split(",")
            lat = float(lat_lon[0].replace("°", "").strip())
            lon = float(lat_lon[1].replace("°", "").strip())

            start_time = datetime.fromisoformat(entry["startTime"]).astimezone(timezone.utc).replace(tzinfo=None)
            end_time = datetime.fromisoformat(entry["endTime"]).astimezone(timezone.utc).replace(tzinfo=None)
            gap = 10
            for t in pd.date_range(start_time, end_time, freq=f"{gap}s"):
                all_points.append({
                    "latitude": lat,
                    "longitude": lon,
                    "timestamp": t,
                    "date": t.date().isoformat(),
                    "interpolated": False,
                })
                dates.add(t.date().isoformat())


        if "activity" in entry:
            start_lat_lon = entry["activity"]["start"]["latLng"].split(",")
            end_lat_lon = entry["activity"]["end"]["latLng"].split(",")

            start_lat = float(start_lat_lon[0].replace("°", "").strip())
            start_lon = float(start_lat_lon[1].replace("°", "").strip())

            end_lat = float(end_lat_lon[0].replace("°", "").strip())
            end_lon = float(end_lat_lon[1].replace("°", "").strip())

            start_time = datetime.fromisoformat(entry["startTime"]).astimezone(timezone.utc).replace(tzinfo=None)
            end_time = datetime.fromisoformat(entry["endTime"]).astimezone(timezone.utc).replace(tzinfo=None)

            # add only start and end points for activities, as they are likely to be more accurate than the interpolated points in between
            all_points.append({
                "latitude": start_lat,
                "longitude": start_lon,
                "timestamp": start_time,
                "date": start_time.date().isoformat(),
                "interpolated": False,
            })

            # interpolate points every 10s between start and end time, but only if the activity is longer than 1 minute
            if (end_time - start_time) > timedelta(minutes=1):
                gap = 10
                for t in pd.date_range(start_time, end_time, freq=f"{gap}s"):
                    ratio = (t - start_time).total_seconds() / (end_time - start_time).total_seconds()
                    lat = start_lat + ratio * (end_lat - start_lat)
                    lon = start_lon + ratio * (end_lon - start_lon)
                    all_points.append({
                        "latitude": lat,
                        "longitude": lon,
                        "timestamp": t,
                        "date": t.date().isoformat(),
                        "interpolated": True,
                    })
                    dates.add(t.date().isoformat())

    all_points = sorted(all_points, key=lambda p: p["timestamp"])
    point_timestamps = [p["timestamp"] for p in all_points]

    dates = sorted(set(dates))
    for date in tqdm(dates):
        assign_gps_to_images(date, all_points, point_timestamps)


    # export to CSV for analysis
    # with open("gps_points.csv", "w") as f:
    #     f.write(",".join(field_names) + "\n")
    #     for point in all_points:
    #         f.write(",".join(str(point.get(name, "")) for name in field_names) + "\n")

    # # After processing all dates, print overall stats, counting how many images have GPS data and how many don't
    # total_images = session.execute(select(Image).where(Image.device == "cathal")).fetchall()
    # total_images = len(total_images)
    # gps_count = session.execute(select(ImageGPS).join(Image, ImageGPS.image_id == Image.id).where(Image.device == "cathal")).fetchall()
    # gps_count = len(gps_count)
    # print("\nOverall Stats:")
    # print(f"Total images: {total_images}")
    # print(f"Images with GPS: {gps_count} ({100*gps_count//total_images}%)")

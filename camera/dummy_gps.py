import json
import os
from datetime import datetime, timedelta, timezone

import pandas as pd
import requests
from dotenv import load_dotenv
from timezonefinder import TimezoneFinder

load_dotenv()

device_id = os.getenv("DEVICE_ID", "omi")
DIR = "/mnt/ssd0/LifelogPicam"
tf = TimezoneFinder()
since_date = datetime(2026, 5, 21, tzinfo=timezone.utc)
to_date = datetime(2026, 6, 7, tzinfo=timezone.utc)


def get_points():
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
            time = datetime.fromisoformat(point["time"])  # this has timezone info
            time = time.astimezone(timezone.utc).replace(tzinfo=None)
            all_points.append(
                {
                    "latitude": lat,
                    "longitude": lon,
                    "timestamp": time,
                    "date": time.date().isoformat(),
                    "interpolated": False,
                }
            )
            dates.add(time.date().isoformat())

        if "visit" in entry:
            lat_lon = entry["visit"]["topCandidate"]["placeLocation"]["latLng"].split(
                ","
            )
            lat = float(lat_lon[0].replace("°", "").strip())
            lon = float(lat_lon[1].replace("°", "").strip())

            start_time = (
                datetime.fromisoformat(entry["startTime"])
                .astimezone(timezone.utc)
                .replace(tzinfo=None)
            )
            end_time = (
                datetime.fromisoformat(entry["endTime"])
                .astimezone(timezone.utc)
                .replace(tzinfo=None)
            )
            gap = 10
            for t in pd.date_range(start_time, end_time, freq=f"{gap}s"):
                all_points.append(
                    {
                        "latitude": lat,
                        "longitude": lon,
                        "timestamp": t,
                        "date": t.date().isoformat(),
                        "interpolated": False,
                    }
                )
                dates.add(t.date().isoformat())

        if "activity" in entry:
            start_lat_lon = entry["activity"]["start"]["latLng"].split(",")
            end_lat_lon = entry["activity"]["end"]["latLng"].split(",")

            start_lat = float(start_lat_lon[0].replace("°", "").strip())
            start_lon = float(start_lat_lon[1].replace("°", "").strip())

            end_lat = float(end_lat_lon[0].replace("°", "").strip())
            end_lon = float(end_lat_lon[1].replace("°", "").strip())

            start_time = (
                datetime.fromisoformat(entry["startTime"])
                .astimezone(timezone.utc)
                .replace(tzinfo=None)
            )
            end_time = (
                datetime.fromisoformat(entry["endTime"])
                .astimezone(timezone.utc)
                .replace(tzinfo=None)
            )

            # add only start and end points for activities, as they are likely to be more accurate than the interpolated points in between
            all_points.append(
                {
                    "latitude": start_lat,
                    "longitude": start_lon,
                    "timestamp": start_time,
                    "date": start_time.date().isoformat(),
                    "interpolated": False,
                }
            )

            # # interpolate points every 10s between start and end time, but only if the activity is longer than 1 minute
            # if (end_time - start_time) > timedelta(minutes=1):
            #     gap = 10
            #     for t in pd.date_range(start_time, end_time, freq=f"{gap}s"):
            #         ratio = (t - start_time).total_seconds() / (
            #             end_time - start_time
            #         ).total_seconds()
            #         lat = start_lat + ratio * (end_lat - start_lat)
            #         lon = start_lon + ratio * (end_lon - start_lon)
            #         all_points.append(
            #             {
            #                 "latitude": lat,
            #                 "longitude": lon,
            #                 "timestamp": t,
            #                 "date": t.date().isoformat(),
            #                 "interpolated": True,
            #             }
            #         )
            #         dates.add(t.date().isoformat())

    all_points = sorted(all_points, key=lambda p: p["timestamp"])
    point_timestamps = [p["timestamp"] for p in all_points]
    return all_points, dates, point_timestamps


if __name__ == "__main__":
    points = "all_points.csv"
    if not os.path.exists(points):
        all_points, dates, point_timestamps = get_points()
        df = pd.DataFrame(all_points)
        df.to_csv(points, index=False)
    else:
        df = pd.read_csv(points)
        all_points = df.to_dict(orient="records")

    all_dates = sorted(set(p["date"] for p in all_points))
    for date in all_dates:
        end_point = "http://localhost:8082/location/upload-gps"
        if date < since_date.date().isoformat() or date > to_date.date().isoformat():
            continue
        if os.path.isdir(f"{DIR}/allie/{date}"):
            print(f"Uploading GPS data for date {date}...")
            points = []
            for point in all_points:
                if point["date"] == date:
                    payload = {
                        "latitude": point["latitude"],
                        "longitude": point["longitude"],
                        "timestamp": point["timestamp"],
                        "t": datetime.fromisoformat(point["timestamp"]),
                        "device_id": device_id,
                    }
                    points.append(payload)

            # Sample GPS data for each second
            every_second_points = []
            t = points[0]["t"]
            for point in points[1:]:
                t2 = point["t"]
                if (t2 - t).total_seconds() >= 1:
                    every_second_points.append(point)
                    t = t2

            for point in every_second_points:
                response = requests.put(
                    end_point,
                    json={
                        "latitude": point["latitude"],
                        "longitude": point["longitude"],
                        "timestamp": point["timestamp"],
                        "device_id": device_id,
                    },
                    timeout=10,
                )
                if response.status_code != 200:
                    print(f"Error sending point: {response.text}")

            end_point = (
                f"http://localhost:8082/location/process-gps?date={date}&device=allie"
            )
            response = requests.get(
                end_point, timeout=10, headers={"X-Device-ID": device_id}
            )
            print(
                f"Processing GPS data for date {date}, Response: {response.status_code}"
            )
            if response.status_code != 200:
                print(f"Error processing GPS data: {response.text}")

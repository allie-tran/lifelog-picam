from datetime import timezone
from tqdm import tqdm
from pymongo import MongoClient
import pandas as pd
from timezonefinder import TimezoneFinder

local_client = MongoClient('mongodb://localhost:27017/')
old_lsc_db = local_client['LSC24_new']['images']

tf = TimezoneFinder()
timezone_cache = {}
def cached_find_timezone(lat, lon):
    if (lat, lon) in timezone_cache:
        return timezone_cache[(lat, lon)]
    tz = tf.timezone_at(lng=lon, lat=lat)
    timezone_cache[(lat, lon)] = tz
    return tz

def move_date(date_str):
    images = old_lsc_db.find({"date": date_str})
    images = list(images)  # Convert cursor to list for multiple iterations
    date = date_str.replace("/", "-")

    all_entries = []
    for image in tqdm(images, desc=f"Moving images for {date_str}"):
        utc_time = image["time"].replace(tzinfo=timezone.utc)
        new_name = utc_time.strftime("%Y%m%d_%H%M%S")
        assert utc_time.timestamp() == image["timestamp"], "Timestamps do not match!"

        # Update the database entry
        new_entry = {
            "image_path": f"{date}/{new_name}.jpg",
            "timestamp": image["timestamp"],
            "date": date,
            "latitude": image["gps"]["lat"],
            "longitude": image["gps"]["lon"],
            "name": image["location"],
            "address": image["address"],
            "is_stop": 1 if image["stop"] else 0,
            "categories": image["location_info"],
            "country": image["country"],
            "fsq_place_id": image.get("fsq_id", None),
            "timezone": cached_find_timezone(round(image["gps"]["lat"], 4), round(image["gps"]["lon"], 4))
        }
        all_entries.append(new_entry)

    return all_entries


if __name__ == "__main__":
    # Get unique dates from the old database
    unique_dates = old_lsc_db.distinct("date")
    print(f"Found {len(unique_dates)} unique dates to process.")
    all_entries = []
    for date in unique_dates:
        if date.startswith("2019") or date.startswith("2020"):
            all_entries.extend(move_date(date))

    df = pd.DataFrame(all_entries)
    df.to_csv("files/lsc24_images.csv", index=False, sep=";")

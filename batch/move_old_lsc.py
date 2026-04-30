import os
from datetime import datetime, timezone

from dotenv import load_dotenv
from PIL import Image as PILImage
from pymongo import MongoClient
from sqlalchemy import create_engine
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session
from tqdm import tqdm
from concurrent.futures import ProcessPoolExecutor

from models import Image

load_dotenv()

OLD_DIR = "/mnt/external/Images/RawLSC23/lsc2022/"
# OLD_THUMBNAIL = "/mnt/ssd0/Images/LSC22/"
OLD_THUMBNAIL = "/mnt/ssd0/Images/LSC23-Luca/images/"

NEW_DIR = "/mnt/ssd0/LifelogPicam/cathal/"
NEW_THUMBNAIL = "/mnt/ssd0/Images/LifelogPicam/cathal/"

PG_URI = os.getenv("PG_URI")  # Your PostgreSQL connection string
assert PG_URI, "PostgreSQL URI must be set in .env"
engine = create_engine(PG_URI)

MONGO_URI = os.getenv("MONGO_URI")  # Your MongoDB connection string
client = MongoClient(MONGO_URI)
old_lsc_db = client["LSC24_new"]["images"]

DEVICE = "cathal"


def process_image(args):
    image_path, thumbnail_path, new_image_path, new_thumbnail_path, time = args
    if os.path.exists(image_path) and os.path.exists(thumbnail_path):
        os.system(f"cp {image_path} {new_image_path}")
        try:
            img = PILImage.open(thumbnail_path)
            img.save(new_thumbnail_path, "WEBP", quality=80, exif=img.getexif())
            # for publishing
            temp = (
                "/mnt/ssd0/Images/LSC26/"
                + time.strftime("%Y/%m/%d/%Y%m%d_%H%M%S.webp")
            )
            os.makedirs(os.path.dirname(temp), exist_ok=True)
            os.system(f"cp {new_thumbnail_path} {temp}")
        except Exception as e:
            print(f"Error processing thumbnail {thumbnail_path}: {e}")
    else:
        if not os.path.exists(image_path):
            print(f"Image file not found: {image_path}")
        if not os.path.exists(thumbnail_path):
            print(f"Thumbnail file not found: {thumbnail_path}")


def move_date(date_str):
    images = old_lsc_db.find({"date": date_str})
    images = list(images)  # Convert cursor to list for multiple iterations
    date = date_str.replace("/", "-")

    to_process = []
    to_insert = []
    for image in images:
        image_path = image["image"]
        full_path = f"{OLD_DIR}{image_path}"
        thumbnail_path = f"{OLD_THUMBNAIL}{image_path.split('.')[0]}.jpg"
        old_name = os.path.basename(image_path)

        time = datetime.strptime(old_name.split(".")[0], "%Y%m%d_%H%M%S_%f")
        utc_time = time.replace(tzinfo=timezone.utc)

        # new_name = utc_time.strftime('%Y%m%d_%H%M%S')
        new_name = time.strftime("%Y%m%d_%H%M%S")
        new_image_path = f"{NEW_DIR}{date}/{new_name}.jpg"

        new_thumbnail_path = f"{NEW_THUMBNAIL}{date}/{new_name}.webp"
        os.makedirs(os.path.dirname(new_image_path), exist_ok=True)
        os.makedirs(os.path.dirname(new_thumbnail_path), exist_ok=True)
        # if os.path.exists(new_image_path) and os.path.exists(new_thumbnail_path):
        #     continue
        to_process.append(
            (full_path, thumbnail_path, new_image_path, new_thumbnail_path, time)
        )
        to_insert.append((image, date, new_name, utc_time, time))

    with ProcessPoolExecutor(max_workers=16) as executor:
        list(
            tqdm(
                executor.map(process_image, to_process),
                total=len(to_process),
                desc=f"Processing images for {date_str}",
            )
        )

    return
    with Session(engine) as session:
        for image, date, new_name, utc_time, time in tqdm(
            to_insert, desc=f"Inserting DB entries for {date_str}"
        ):
            # Update the database entry
            new_entry = {
                "device": "cathal",
                "mongo_id": str(image["_id"]),
                "image_path": f"{date}/{new_name}.jpg",
                "thumbnail": f"{date}/{new_name}.webp",
                "is_video": False,
                "timestamp": utc_time,
                "local_timestamp": time,
                "date": date,
                "year": time.year,
                "month": time.month,
                "day": time.day,
                "hour": time.hour,
                "seconds_from_midnight": time.hour * 3600
                + time.minute * 60
                + time.second,
                "deleted": False,
                "deleted_time": None,
                "activity": "",
                "activity_description": "",
                "activity_confidence": "",
                "new": True,
                "proc_encoded": False,
                "proc_yolo": False,
                "proc_ocr": False,
                "proc_deepface": False,
                "proc_insightface": False,
            }

            stmt = insert(Image).values(**new_entry).on_conflict_do_nothing()
            stmt = stmt.returning(Image.id)
            img_id = session.execute(stmt).scalar()
        session.commit()


if __name__ == "__main__":
    # Get unique dates from the old database
    unique_dates = old_lsc_db.distinct("date")
    print(f"Found {len(unique_dates)} unique dates to process.")
    for date in unique_dates:
        if date.startswith("2019") or date.startswith("2020"):
            move_date(date)

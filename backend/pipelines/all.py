from scripts.object_detection import extract_object_from_image
from database.types import ImageRecord, ProcessedInfo
from datetime import datetime
from preprocess import compress_image, encode_image, make_video_thumbnail
from constants import DIR
from app_types import CustomFastAPI

def process_image(app: CustomFastAPI, date: str, file_name: str):
    if f"{date}/{file_name}" not in app.image_paths:
        _, app.features, app.image_paths = encode_image(
            f"{date}/{file_name}", app.features, app.image_paths
        )

    compress_image(f"{DIR}/{date}/{file_name}")
    relative_path = f"{date}/{file_name}"
    timestamp = datetime.strptime(file_name.split(".")[0], "%Y%m%d_%H%M%S")
    objects, people = extract_object_from_image(f"{DIR}/{relative_path}")

    ImageRecord(
        date=date,
        image_path=relative_path,
        thumbnail=relative_path.replace(".jpg", ".webp"),
        timestamp=timestamp.timestamp() * 1000,  # Convert to milliseconds
        is_video=False,
        objects=objects,
        people=people,
        processed=ProcessedInfo(yolo=True, encoded=True)
    ).create()

    return app

def process_video(app: CustomFastAPI, date: str, file_name: str):
    output_path = f"{DIR}/{date}/{file_name}"
    timestamp = datetime.strptime(file_name.split(".")[0], "%Y%m%d_%H%M%S")
    make_video_thumbnail(output_path)
    ImageRecord(
        image_path=f"{date}/{file_name}",
        thumbnail=f"{date}/{file_name.split('.')[0]}.webp",
        date=date,
        timestamp=timestamp.timestamp() * 1000,  # Convert to milliseconds
        is_video=True,
    ).create()

    if output_path not in app.image_paths:
        _, app.features, app.image_paths = encode_image(
            output_path, app.features, app.image_paths
        )

    return app


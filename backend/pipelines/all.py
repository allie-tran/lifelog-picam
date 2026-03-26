from collections import defaultdict
from datetime import datetime, timezone
import os
from typing import Optional

from sqlalchemy import insert, update
from sqlalchemy.sql import select
import zvec
from auth.ortho import apply_transformation, get_matrix
from auth.types import Person
from constants import DIR
from pipelines.delete import remove_physical_images
from scripts.utils import get_thumbnail_path, make_video_thumbnail
from tasks import anonymise_image_task, yolo_process_images_task
from visual import clip_model
from database.models import Device, DeviceWhitelistEmbedding, DeviceWhitelistEntry, Image, ImageEmbedding, ImagePerson


# def find_segment(session, device_id: str, timestamp: float) -> int | None:
#     # Find the segment ID for the given image path and timestamp
#     end = session.select(Image).where(
#         Image.timestamp >= timestamp,
#         Image.segment_id.isnot(None),
#         Image.device == device_id,
#     ).order_by(Image.timestamp.asc()).limit(1)
#     end = session.execute(end).scalars().first()
#     if not end:
#         # This should belong to a new segment
#         return None

#     start = session.select(Image).where(
#         Image.timestamp <= timestamp,
#         Image.segment_id.isnot(None),
#         Image.device == device_id,
#     ).order_by(Image.timestamp.desc()).limit(1)

#     if not start:
#         # This should never happen, but just in case
#         print("Warning: No start segment found for timestamp", timestamp)
#         return None

#     if start.segment_id == end.segment_id:
#         return start.segment_id

#     # Reset all the segments that are greater than end.segment_id
#     session.execute(
#         update(Image)
#         .where(Image.segment_id > end.segment_id, Image.device == device_id)
#         .values(segment_id=Image.segment_id + 1)
#     )


def index_to_postgres(
    session, device_id: str, relative_path: str, skip_segmentation: bool = False
):
    date, file_name = relative_path.split("/")
    local_timestamp = datetime.strptime(file_name, "%Y%m%d_%H%M%S_%Z.jpg")
    timestamp = local_timestamp.astimezone(timezone.utc)

    session.execute(
        insert(Image).values(
            date=date,
            device=device_id,
            image_path=relative_path,
            thumbnail=relative_path.replace(".jpg", ".webp"),
            timestamp=timestamp.replace(tzinfo=timezone.utc),
            local_timestamp=local_timestamp,
            year=local_timestamp.year,
            month=local_timestamp.month,
            day=local_timestamp.day,
            hour=local_timestamp.hour,
            seconds_from_midnight=local_timestamp.hour * 3600 + local_timestamp.minute * 60 + local_timestamp.second,
            is_video=False,
            proc_yolo=False,
            proc_encoded=False,
            proc_sam3=False,
            proc_ocr=False,
            proc_insightface=False,
            segment_id=None,
        )
    )


def yolo_process_images(
    device_id: str,
    white_list: list[Person],
    relative_paths: list[str],
):
    paths = []
    for path in relative_paths:
        image_path = f"{DIR}/{device_id}/{path}"
        paths.append(image_path)

    yolo_process_images_task.delay(
        device_id,
        paths,
        [person.name for person in white_list],
        [person.embeddings for person in white_list],
    )


def create_thumbnail(session, device_id: str, relative_path: str, skip_sam3=False):
    thumbnail_path, thumbnail_exists = get_thumbnail_path(
        f"{DIR}/{device_id}/{relative_path}"
    )
    # get whitelist people
    res = session.execute(
        select(ImagePerson)
        .where(Image.image_path == relative_path, Image.device == device_id)
        .join(Image, Image.id == ImagePerson.image_id)
    ).fetchall()
    boxes = []
    whitelist_boxes = []
    for person in res:
        if person.label != "redacted face" and person.label != "face":
            whitelist_boxes.append(person.bbox)
        else:
            boxes.append(person.bbox)

    if not thumbnail_exists:
        anonymise_image_task.delay(
            f"{DIR}/{device_id}/{relative_path}",
            thumbnail_path,
            boxes,
            whitelist_boxes,
            skip_sam3=skip_sam3,
        )

    session.execute(
        update(Image)
        .where(Image.image_path == relative_path, Image.device == device_id)
        .values(proc_sam3=True, thumbnail=relative_path.replace(".jpg", ".webp"))
    )
    session.commit()


def encode_image(
    session,
    device_id: str,
    image_path: str,
    matrix: Optional[list[list[float]]] = None,
):
    try:
        path = f"{DIR}/{device_id}/{image_path}"
        if image_path.endswith(".mp4") or image_path.endswith(".h264"):
            # use video thumbnail
            new_path = make_video_thumbnail(f"{DIR}/{device_id}/{image_path}")
            if new_path:
                path = new_path

        vector = clip_model.encode_image(path)
        vector = vector.flatten()
        vector = apply_transformation(
            vector, matrix if matrix else get_matrix(session, device_id)
        )
        session.execute(
            insert(ImageEmbedding).values(
                image_id=session.execute(
                    select(Image.id).where(
                        Image.image_path == image_path, Image.device == device_id
                    )
                ).scalar_one(),
                embedding=vector,
            )
        )
        session.commit()

    except Exception as e:
        print(e)
        print(f"Error encoding image {image_path}")
        if os.path.exists(f"{DIR}/{device_id}/{image_path}"):
            os.remove(f"{DIR}/{device_id}/{image_path}")


def process_image(
    session,
    device_id: str,
    date: str,
    file_name: str,
):
    relative_path = f"{date}/{file_name}"
    try:
        index_to_postgres(session, device_id, relative_path)
        # white_list = []
        # if device:
        #     white_list = device.whitelist
        white_list = []

        white_list_entrys = session.execute(
            select(DeviceWhitelistEntry)
            .where(DeviceWhitelistEntry.device_id == session.execute(select(Device.id).where(Device.device_id == device_id)).scalar_one())
        ).scalars().all()
        ids = [entry.id for entry in white_list_entrys]

        white_list_embeddings = session.execute(
            select(DeviceWhitelistEmbedding)
            .where(DeviceWhitelistEmbedding.entry_id.in_(ids))
        ).scalars().all()
        embeddings_by_entry = defaultdict(list)
        for embedding in white_list_embeddings:
            embeddings_by_entry[embedding.entry_id].append(embedding.embedding)

        for entry in white_list_entrys:
            white_list.append(
                Person(
                    name=entry.name,
                    cropped=entry.cropped,
                    embeddings=embeddings_by_entry.get(entry.id, []),
                )
            )

        yolo_process_images(device_id, white_list, [relative_path])
        create_thumbnail(session, device_id, relative_path)
        encode_image(session, device_id, relative_path)

    except FileNotFoundError as e:
        print(
            f"Error processing image {file_name} for device {device_id} on date {date}: {e}"
        )
        remove_physical_images(session, device_id, [relative_path])


def process_video(
    device_id: str, date: str, file_name: str, collection: Optional[zvec.Collection]
):
    raise NotImplementedError("Video processing is not implemented yet")
    # output_path = f"{DIR}/{device_id}/{date}/{file_name}"
    # assert collection, "Collection must be provided for processing images"
    # timestamp = datetime.strptime(file_name.split(".")[0], "%Y%m%d_%H%M%S_%Z")
    # make_video_thumbnail(output_path)
    # ImageRecord(
    #     device=device_id,
    #     image_path=f"{date}/{file_name}",
    #     thumbnail=f"{date}/{file_name.split('.')[0]}.webp",
    #     date=date,
    #     timestamp=timestamp.timestamp() * 1000,  # Convert to milliseconds
    #     is_video=True,
    # ).create()

    # encode_image(device_id, f"{date}/{file_name}", collection)

from collections import defaultdict
from datetime import timezone
from typing import Optional
import traceback

from sqlalchemy import func, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.sql import select
from auth.ortho import apply_transformation, get_matrix
from auth.types import Person
from constants import DIR
from pipelines.delete import remove_physical_images
from scripts.date_utils import parse_date
from scripts.utils import make_video_thumbnail
from tasks import yolo_process_images_task
from visual import clip_model, SIGLIP
from database.models import Base, Device, DeviceWhitelistEmbedding, DeviceWhitelistEntry, Image, ImageEmbedding, ImagePerson
from sqlalchemy.exc import SQLAlchemyError
from visual.siglip import SIGLIP
import logging


def index_to_postgres(
    session, device_id: str, relative_path: str, tz: str,
    skip_segmentation: bool = False,
):
    date, file_name = relative_path.split("/")
    if "-" in file_name:
        return  # skip already processed files that have been renamed with a dash

    local_timestamp = parse_date(file_name.split(".")[0])
    utc_time = local_timestamp.astimezone(timezone.utc)

    stmt = insert(Image).values(
            date=date,
            device=device_id,
            image_path=relative_path,
            thumbnail=relative_path.replace(".jpg", ".webp"),
            timestamp=utc_time.replace(tzinfo=None),
            timezone=tz,
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
    stmt = stmt.on_conflict_do_nothing(
        index_elements=["device", "image_path"]
    )
    session.execute(stmt)
    session.commit()


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
    # anonymise_image_task is dispatched by yolo_process_images_task after
    # detection results are written, so it isn't dispatched here anymore.
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
    SQLTable: Base.__class__ = ImageEmbedding,
    model: SIGLIP = clip_model,
):
    try:
        path = f"{DIR}/{device_id}/{image_path}"
        if image_path.endswith(".mp4") or image_path.endswith(".h264"):
            # use video thumbnail
            new_path = make_video_thumbnail(f"{DIR}/{device_id}/{image_path}")
            if new_path:
                path = new_path

        vector = model.encode_image(path)
        vector = vector.flatten()
        if matrix is None:
            matrix = get_matrix(session, device_id)
        vector = apply_transformation(
            vector, matrix
        )
        image_id = session.execute(
            select(Image.id).where(
                Image.image_path == image_path, Image.device == device_id
            )
        ).scalar_one_or_none()
        if image_id is None:
            raise ValueError(f"Image record not found for device {device_id} and path {image_path}")

        session.execute(
            insert(SQLTable).values(
                image_id=image_id,
                embedding=vector,
            ).on_conflict_do_update(
                index_elements=["image_id"],
                set_={"embedding": vector},
            )
        )
        session.commit()

    except SQLAlchemyError as e:
        error = str(e.__dict__.get("orig"))  # Get the original error message from SQLAlchemy
        print(f"Database error encoding image {image_path}: {error}")
        raise(e)

    except Exception as e:
        traceback.print_exc()
        print(f"Error encoding image {image_path}")


def process_image(
    session,
    device_id: str,
    date: str,
    file_name: str,
    tz: str,
):
    relative_path = f"{date}/{file_name}"
    try:
        index_to_postgres(session, device_id, relative_path, tz)
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

        session.commit()
        session.flush()
        session.expire_all()  # Clear the session cache to get the latest data from the database
        yolo_process_images(device_id, white_list, [relative_path])
        create_thumbnail(session, device_id, relative_path)
        encode_image(session, device_id, relative_path)

    except FileNotFoundError as e:
        print(
            f"Error processing image {file_name} for device {device_id} on date {date}: {e}"
        )
        remove_physical_images(session, device_id, [relative_path])


def process_video(
    device_id: str, date: str, file_name: str
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

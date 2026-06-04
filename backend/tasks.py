from sqlalchemy import create_engine, insert, select, update
from sqlalchemy.orm import Session, selectinload
from auth.ortho import get_matrix
from auth.types import Person
from celery_app import celery
from database.models import Image, ImageEmbedding, ImageObject, ImagePerson
from scripts.anonymise import anonymise_image
from scripts.describe_segments import describe_segment, simple_describe_segment
from pymongo import MongoClient
import logging

from scripts.object_detection import ModelWrapper, extract_object_from_images
import os


logging.info("Starting Celery worker for describe_segment_task...")
PG_URI = os.getenv("PG_URI", "postgresql://postgres:password@localhost:5432/picam")
engine = create_engine(PG_URI)

class MyTask(celery.Task):
    def __init__(self):
        self.sessions = {}

    def before_start(self, task_id, args, kwargs):
        self.sessions[task_id] = Session(engine)  # Create a new session for this task
        super().before_start(task_id, args, kwargs)

    def after_return(self, status, retval, task_id, args, kwargs, einfo):
        session = self.sessions.pop(task_id)
        session.flush()  # Flush any pending changes to the database
        session.close()
        super().after_return(status, retval, task_id, args, kwargs, einfo)

    @property
    def session(self):
        return self.sessions[self.request.id]


@celery.task(name="tasks.describe_segment_task", base=MyTask, bind=True)
def describe_segment_task(
    self,
    device, date, thumbnail_paths, segment_id, extra_info: list[str] = []
):
    mongo_client = MongoClient("mongodb://localhost:27017/")
    try:
        activity_obj = describe_segment(
            device,
            date,
            thumbnail_paths,
            segment_id=segment_id,
            extra_info=extra_info,
        )
        # stmt = select(ImageEmbedding.embedding).join(Image).where(
        #     Image.device == device,
        #     Image.segment_id == segment_id,
        #     Image.date == date,
        # )
        # embeddings = [r.embedding for r in self.session.execute(stmt).fetchall()]
        # logging.info(f"Retrieved {len(embeddings)} embeddings for segment {segment_id} of device {device} on date {date}")

        # activity_obj = simple_describe_segment(
        #     embeddings=embeddings,
        #     matrix=get_matrix(self.session, device),
        #     segment_id=segment_id,
        # )

        stmt = update(Image).where(
                Image.device == device,
                Image.segment_id == segment_id,
                Image.date == date,
            ).values(activity=activity_obj["activity"], activity_description=activity_obj["activity_description"], activity_confidence=activity_obj["activity_confidence"])

        logging.info(f"Updating database for segment {segment_id} with activity '{activity_obj['activity']}' and confidence '{activity_obj['activity_confidence']}'")
        pg_result = self.session.execute(stmt)
        logging.info(f"Updated {pg_result.rowcount} rows in the database for segment {segment_id}")
        self.session.commit()

        mongo_client["picam"]["day_summaries"].update_one(
            {"date": date, "device": device},
            {"$set": {"updated": True}},
            upsert=True,
        )
    except Exception as e:
        logging.error(
            f"Error describing segment {segment_id} for {device} on {date}: {e}"
        )


@celery.task(name="tasks.yolo_process_images_task", base=MyTask, bind=True)
def yolo_process_images_task(
    self,
    device,
    paths,
    whitelist_names: list[str] = [],
    whitelist_embeddings: list[list[list[float]]] = [],
):
    logging.info(f"Starting YOLO processing for device {device} with {len(paths)} images")
    if not paths:
        logging.info(f"No paths provided for YOLO processing for device {device}")
        return
    whitelist = [
        Person(name=name, embeddings=embedding, cropped=[""])
        for name, embedding in zip(whitelist_names, whitelist_embeddings)
    ]
    results = extract_object_from_images(paths, whitelist)

    # Get image_ids from paths
    relative_paths = [path.split(f"{device}/")[1] for path in paths]
    stmt = select(Image.id, Image.image_path).where(
        Image.device == device, Image.image_path.in_(relative_paths)
    )
    pg_results = self.session.execute(stmt).fetchall()
    image_id_map = {r.image_path: r.id for r in pg_results}

    object_rows = []
    person_rows = []
    image_rows = []
    for r in results:
        image_path = r["image_path"]
        objects = r["objects"]
        people = r["people"]
        relative_path = image_path.split(f"{device}/")[1]
        if image_id_map.get(relative_path) is None:
            continue

        image_id = image_id_map[relative_path]

        for obj in objects:
            obj = obj.model_dump()
            object_rows.append(
                {
                    "image_id": image_id,
                    "label": obj["label"],
                    "confidence": obj["confidence"],
                    "bbox": obj["bbox"],
                    "rel_bbox": obj["rel_bbox"],
                }
            )

        for person in people:
            person = person.model_dump()
            person_rows.append(
                {
                    "image_id": image_id,
                    "label": person["label"],
                    "confidence": person["confidence"],
                    "bbox": person["bbox"],
                    "rel_bbox": person["rel_bbox"],
                    "embedding": person["embedding"],
                }
            )
        image_rows.append(relative_path)

    if object_rows:
        self.session.execute(insert(ImageObject).values(object_rows))
        logging.info(f"Inserted {len(object_rows)} objects into the database")
    if person_rows:
        self.session.execute(insert(ImagePerson).values(person_rows))
        logging.info(f"Inserted {len(person_rows)} people into the database")

    self.session.execute(
        update(Image)
        .where(Image.image_path.in_(image_rows), Image.device == device)
        .values(
            proc_yolo=True,
            proc_insightface=True,
            proc_deepface=False,
        )
    )
    logging.info(f"Updated {len(image_rows)} images as processed for YOLO and InsightFace")

    self.session.commit()


@celery.task(name="tasks.anonymise_image_task")
def anonymise_image_task(path, thumbnail_path, boxes, whitelist_boxes, skip_sam3=False):
    anonymise_image(path, thumbnail_path, boxes, whitelist_boxes, skip_sam3=skip_sam3)
    return thumbnail_path

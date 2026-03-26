from sqlalchemy import create_engine, insert, select, update
from sqlalchemy.orm import Session
from auth.types import Person
from celery_app import celery
from database.models import Image, ImageObject, ImagePerson
from scripts.anonymise import anonymise_image
from scripts.describe_segments import describe_segment
from pymongo import MongoClient
import logging

from scripts.object_detection import extract_object_from_images

import os


logging.basicConfig(
    level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s"
)
logging.info("Starting Celery worker for describe_segment_task...")
PG_URI = os.getenv("PG_URI", "postgresql://postgres:password@localhost:5432/picam")


@celery.task(name="tasks.describe_segment_task")
def describe_segment_task(
    device, date, thumbnail_paths, segment_id, extra_info: list[str] = []
):
    mongo_client = MongoClient("mongodb://localhost:27017/")
    engine = create_engine(PG_URI)
    with Session(engine) as session:
        try:
            activity_obj = describe_segment(
                device,
                date,
                thumbnail_paths,
                segment_id=segment_id,
                extra_info=extra_info,
            )

            stmt = update(Image).where(
                    Image.device == device,
                    Image.segment_id == segment_id,
                    Image.date == date,
                ).values(activity=activity_obj["activity"], activity_description=activity_obj["activity_description"], activity_confidence=activity_obj["activity_confidence"])

            logging.info(f"Updating database for segment {segment_id} with activity '{activity_obj['activity']}' and confidence '{activity_obj['activity_confidence']}'")
            pg_result = session.execute(stmt)
            logging.info(f"Updated {pg_result.rowcount} rows in the database for segment {segment_id}")
            session.commit()
            session.flush()

            mongo_client["picam"]["day_summaries"].update_one(
                {"date": date, "device": device},
                {"$set": {"updated": True}},
                upsert=True,
            )
        except Exception as e:
            logging.error(
                f"Error describing segment {segment_id} for {device} on {date}: {e}"
            )


@celery.task(name="tasks.yolo_process_images_task")
def yolo_process_images_task(
    device,
    paths,
    whitelist_names: list[str] = [],
    whitelist_embeddings: list[list[list[float]]] = [],
):
    engine = create_engine(PG_URI)

    whitelist = [
        Person(name=name, embeddings=embedding, cropped=[""])
        for name, embedding in zip(whitelist_names, whitelist_embeddings)
    ]
    results = extract_object_from_images(paths, whitelist)

    with Session(engine) as session:
        # Get image_ids from paths
        relative_paths = [path.split(f"{device}/")[1] for path in paths]
        stmt = select(Image.id, Image.image_path).where(
            Image.device == device, Image.image_path.in_(relative_paths)
        )
        pg_results = session.execute(stmt).fetchall()
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
                        "embedding": person["embedding"],
                        "cluster_label": None,
                    }
                )
            image_rows.append(relative_path)

        if object_rows:
            session.execute(insert(ImageObject).values(object_rows))
            logging.info(f"Inserted {len(object_rows)} objects into the database")
        if person_rows:
            session.execute(insert(ImagePerson).values(person_rows))
            logging.info(f"Inserted {len(person_rows)} people into the database")
        session.execute(
            update(Image)
            .where(Image.image_path.in_(image_rows), Image.device == device)
            .values(
                proc_yolo=True,
                proc_insightface=True,
                proc_deepface=False,
            )
        )

        session.commit()
        session.flush()


@celery.task(name="tasks.anonymise_image_task")
def anonymise_image_task(path, thumbnail_path, boxes, whitelist_boxes, skip_sam3=False):
    anonymise_image(path, thumbnail_path, boxes, whitelist_boxes, skip_sam3=skip_sam3)

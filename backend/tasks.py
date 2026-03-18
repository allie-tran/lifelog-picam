from auth.types import Person
from celery_app import celery
from scripts.anonymise import anonymise_image
from scripts.describe_segments import describe_segment
from pymongo import MongoClient
import logging

from scripts.object_detection import extract_object_from_images

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logging.info("Starting Celery worker for describe_segment_task...")

@celery.task(name="tasks.describe_segment_task")
def describe_segment_task(
    device,
    date,
    thumbnail_paths,
    segment_id,
    extra_info:list[str] = []
):
    mongo_client = MongoClient("mongodb://localhost:27017/")
    try:
        describe_segment(
            mongo_client["picam"]["users"],
            device,
            date,
            thumbnail_paths,
            segment_id=segment_id,
            extra_info=extra_info,
        )
        mongo_client["picam"]["day_summaries"].update_one(
            {"date": date, "device": device},
            {"$set": {"updated": True}},
            upsert=True,
        )
    except Exception as e:
        logging.error(f"Error describing segment {segment_id} for {device} on {date}: {e}")

@celery.task(name="tasks.yolo_process_images_task")
def yolo_process_images_task(
    device,
    paths,
    whitelist_names: list[str] = [],
    whitelist_embeddings: list[list[list[float]]] = [],
):
    mongo_client = MongoClient("mongodb://localhost:27017/")
    collection = mongo_client["picam"]["images"]
    whitelist = [Person(name=name, embeddings=embedding, cropped=[""]) for name, embedding in zip(whitelist_names, whitelist_embeddings)]
    results = extract_object_from_images(
        paths, whitelist
    )

    for r in results:
        image_path = r["image_path"]
        objects = r["objects"]
        people = r["people"]
        relative_path = image_path.split(f"{device}/")[1]

        collection.update_one(
            {"device": device, "image_path": relative_path},
            {
                "$set": {
                    "objects": [obj.model_dump() for obj in objects],
                    "people": [person.model_dump() for person in people],
                    "processed.yolo": True,
                    "processed.insightface": True,
                    "processed.deepface": False,
                }
            },
        )

        # if face_collection:
        #     new_record = ImageRecord.find_one(
        #         {"device": device_id, "image_path": relative_path}
        #     )
        #     assert new_record, "New record not found after YOLO processing"
        #     index_face_embeddings(collection, new_record)

@celery.task(name="tasks.anonymise_image_task")
def anonymise_image_task(
    path,
    thumbnail_path,
    boxes,
    whitelist_boxes,
    skip_sam3=False
):
    anonymise_image(
        path,
        thumbnail_path,
        boxes,
        whitelist_boxes,
        skip_sam3=skip_sam3
    )

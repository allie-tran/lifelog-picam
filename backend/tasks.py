# from celery_app import celery
# from pipelines.all import process_video, process_image
# from pipelines.hourly import update_app
# import zvec
# from pymongo import MongoClient
# from scripts.describe_segments import describe_segment


# @celery.task(name="tasks.process_image_task")
# def process_image_task(
#     device, date, file_name, conclip_collection_name, face_collection_name
# ):
#     """
#     Note: we pass collection *names* (strings) instead of collection objects
#     because Celery tasks must be JSON-serializable.
#     The task re-creates the DB connections in the worker process.
#     """
#     client = MongoClient("mongodb://localhost:27017/")
#     mongo_collection = client["picam"]["images"]
#     clip_collection = zvec.open(conclip_collection_name)
#     face_collection = zvec.open(face_collection_name)
#     process_image(
#         device, date, file_name, mongo_collection, clip_collection, face_collection
#     )
#     print(f"Finished processing image: {file_name}")


# @celery.task(name="tasks.process_video_task")
# def process_video_task(
#     device, date, file_name, conclip_collection_name, face_collection_name
# ):
#     client = MongoClient("mongodb://localhost:27017/")
#     mongo_collection = client["picam"]["images"]
#     clip_collection = zvec.open(conclip_collection_name)
#     face_collection = zvec.open(face_collection_name)
#     process_video(
#         device, date, file_name, mongo_collection, clip_collection, face_collection
#     )


# @celery.task(name="tasks.update_app_task")
# def update_app_task(
#     clip_collection_paths: dict[str, str],
#     face_collection_paths: dict[str, str],
#     to_sync: bool = False,
#     job_id=None,
# ):
#     print("Updating app with new data...")
#     client = MongoClient("mongodb://localhost:27017/")
#     update_app(
#         client,
#         devices=list(clip_collection_paths.keys()),
#         clip_collection_paths=clip_collection_paths,
#         face_collection_paths=face_collection_paths,
#         to_sync=to_sync,
#         job_id=job_id,
#     )

from celery_app import celery
from scripts.describe_segments import describe_segment
from pymongo import MongoClient
import logging

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

from sqlalchemy import create_engine, insert, select, update
from sqlalchemy.orm import Session, selectinload
from auth.ortho import get_matrix
from auth.types import Person
from celery_app import celery
from database.models import Image, ImageEmbedding, ImageObject, ImagePerson, PeopleCluster
from scripts.anonymise import anonymise_image
from scripts.describe_segments import describe_segment, simple_describe_segment
from pymongo import MongoClient
import logging
import uuid
import numpy as np

from scripts.object_detection import ModelWrapper, extract_object_from_images
import os

# Cosine distance threshold for assigning a face to an existing cluster.
# Below this distance → same person; above → new cluster.
_FACE_CLUSTER_THRESHOLD = 0.40


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

        # Incremental dirty flag: record which segment changed rather than
        # invalidating the whole day summary at once.
        mongo_client["picam"]["day_summaries"].update_one(
            {"date": date, "device": device},
            {
                "$addToSet": {"dirty_segment_ids": segment_id},
                "$set": {"text_summary_stale": True, "updated": True},
            },
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

    # Trigger incremental location + face-cluster updates for affected dates
    dates = list({p.split("/")[0] for p in relative_paths if "/" in p})
    for date in dates:
        update_location_task.delay(device, date)
    recluster_unassigned_faces_task.delay(device)


@celery.task(name="tasks.update_location_task", base=MyTask, bind=True)
def update_location_task(self, device: str, date: str):
    """
    Run the GPS → location pipeline for device/date.
    Called automatically after YOLO processes new images so that location_id
    is populated without waiting for a manual trigger.
    """
    from location.gps_pipeline import run_pipeline
    try:
        run_pipeline(self.session, device, date)
        logging.info("Location pipeline complete for %s/%s", device, date)
    except Exception as e:
        logging.error("update_location_task failed for %s/%s: %s", device, date, e)


@celery.task(name="tasks.recluster_unassigned_faces_task", base=MyTask, bind=True)
def recluster_unassigned_faces_task(self, device: str):
    """
    Incrementally assign ImagePerson rows that have an embedding but no cluster_id
    to the nearest existing PeopleCluster, or create a new cluster.

    Algorithm:
      - For each unassigned face: compute cosine distance to every cluster centroid.
      - If nearest distance < _FACE_CLUSTER_THRESHOLD → assign; update centroid online.
      - Else → create new cluster (label = 'Unknown').
    This is called after every YOLO batch so clusters stay fresh without a
    full nightly re-clustering run.
    """
    # Load all unassigned face embeddings for this device
    rows = self.session.execute(
        select(ImagePerson)
        .join(Image, Image.id == ImagePerson.image_id)
        .where(
            Image.device == device,
            ImagePerson.cluster_id.is_(None),
            ImagePerson.embedding.isnot(None),
        )
    ).scalars().all()

    if not rows:
        logging.debug("No unassigned faces for device %s", device)
        return

    # Load all existing clusters
    clusters = self.session.execute(select(PeopleCluster)).scalars().all()
    # Build centroid matrix: shape (C, 512)
    if clusters:
        centroid_ids = [c.id for c in clusters]
        centroid_matrix = np.array([np.array(c.center_embedding) for c in clusters], dtype=np.float32)
        centroid_matrix /= np.linalg.norm(centroid_matrix, axis=1, keepdims=True) + 1e-8
        # Track how many faces are in each cluster (for online centroid update)
        cluster_counts = {c.id: 1 for c in clusters}
    else:
        centroid_ids = []
        centroid_matrix = np.empty((0, 512), dtype=np.float32)
        cluster_counts = {}

    assigned = 0
    created = 0

    for person in rows:
        emb = np.array(person.embedding, dtype=np.float32)
        norm = np.linalg.norm(emb)
        if norm < 1e-8:
            continue
        emb_norm = emb / norm

        if len(centroid_ids) > 0:
            # Cosine distance = 1 - dot(emb_norm, centroid_row)
            distances = 1.0 - (centroid_matrix @ emb_norm)
            best_idx = int(np.argmin(distances))
            best_dist = float(distances[best_idx])
        else:
            best_dist = 1.0
            best_idx = -1

        if best_dist < _FACE_CLUSTER_THRESHOLD:
            # Assign to existing cluster; online centroid update (running mean)
            cluster_id = centroid_ids[best_idx]
            n = cluster_counts[cluster_id]
            new_centroid = (centroid_matrix[best_idx] * n + emb_norm) / (n + 1)
            new_centroid /= np.linalg.norm(new_centroid) + 1e-8
            centroid_matrix[best_idx] = new_centroid
            cluster_counts[cluster_id] += 1
            # Persist centroid update
            self.session.execute(
                update(PeopleCluster)
                .where(PeopleCluster.id == cluster_id)
                .values(center_embedding=new_centroid.tolist())
            )
            assigned += 1
        else:
            # Create new cluster
            new_id = uuid.uuid4()
            self.session.execute(
                insert(PeopleCluster).values(
                    id=new_id,
                    cluster_label="Unknown",
                    center_embedding=emb_norm.tolist(),
                )
            )
            cluster_id = new_id
            # Append to in-memory arrays
            centroid_ids.append(new_id)
            centroid_matrix = np.vstack([centroid_matrix, emb_norm[np.newaxis, :]])
            cluster_counts[new_id] = 1
            created += 1

        self.session.execute(
            update(ImagePerson)
            .where(ImagePerson.id == person.id)
            .values(cluster_id=cluster_id)
        )

    self.session.commit()

    # Invalidate the /all-faces in-process cache so next request reflects new clusters
    from apis.explore import _FACES_CACHE
    _FACES_CACHE.pop(device, None)

    logging.info(
        "Face re-cluster for %s: %d assigned to existing, %d new clusters created.",
        device, assigned, created,
    )


@celery.task(name="tasks.anonymise_image_task")
def anonymise_image_task(path, thumbnail_path, boxes, whitelist_boxes, skip_sam3=False):
    anonymise_image(path, thumbnail_path, boxes, whitelist_boxes, skip_sam3=skip_sam3)
    return thumbnail_path


@celery.task(name="tasks.compute_bio_day_stats_task", base=MyTask, bind=True)
def compute_bio_day_stats_task(self, device_id: str, date: str):
    """Nightly task: compute and upsert BioDayStats for device_id/date."""
    from scripts.bio_stats import compute_and_upsert_bio_day_stats
    try:
        result = compute_and_upsert_bio_day_stats(self.session, device_id, date)
        if result:
            logging.info("Computed bio_day_stats for %s/%s", device_id, date)
        else:
            logging.debug("No bio data for %s/%s, skipped.", device_id, date)
    except Exception as e:
        logging.error("compute_bio_day_stats_task failed for %s/%s: %s", device_id, date, e)


@celery.task(name="tasks.nightly_location_update_all_devices")
def nightly_location_update_all_devices():
    """
    Beat-scheduled: run the GPS→location pipeline for all device/date pairs
    where images still have no location_id assigned.
    """
    from sqlalchemy import create_engine
    from sqlalchemy.orm import Session as SaSession

    engine = create_engine(os.getenv("PG_URI", "postgresql://postgres:password@localhost:5432/picam"))
    with SaSession(engine) as session:
        rows = session.execute(
            select(Image.device, Image.date)
            .where(Image.location_id.is_(None), Image.deleted == False)
            .distinct()
        ).all()

    for device, date in rows:
        update_location_task.delay(device, date)
    logging.info("Queued nightly location updates for %d device/date pairs.", len(rows))


@celery.task(name="tasks.nightly_recluster_all_devices")
def nightly_recluster_all_devices():
    """
    Beat-scheduled: re-cluster unassigned faces for all known camera devices.
    """
    from sqlalchemy import create_engine
    from sqlalchemy.orm import Session as SaSession
    from database.models import Device

    engine = create_engine(os.getenv("PG_URI", "postgresql://postgres:password@localhost:5432/picam"))
    with SaSession(engine) as session:
        device_ids = session.execute(select(Device.device_id)).scalars().all()

    for device_id in device_ids:
        recluster_unassigned_faces_task.delay(device_id)
    logging.info("Queued nightly face re-cluster for %d devices.", len(device_ids))


@celery.task(name="tasks.nightly_bio_stats_all_devices")
def nightly_bio_stats_all_devices():
    """
    Beat-scheduled nightly task.
    Computes bio_day_stats for today and yesterday across all known sensor devices.
    """
    from datetime import datetime, timedelta
    from sqlalchemy import create_engine
    from sqlalchemy.orm import Session as SaSession
    from database.models import SensorDevice

    engine = create_engine(os.getenv("PG_URI", "postgresql://postgres:password@localhost:5432/picam"))
    today = datetime.utcnow().strftime("%Y-%m-%d")
    yesterday = (datetime.utcnow() - timedelta(days=1)).strftime("%Y-%m-%d")

    with SaSession(engine) as session:
        device_ids = session.execute(
            __import__("sqlalchemy").select(SensorDevice.device_id)
        ).scalars().all()

    for device_id in device_ids:
        for date in (today, yesterday):
            compute_bio_day_stats_task.delay(device_id, date)

    logging.info("Queued nightly bio_day_stats for %d devices.", len(device_ids))

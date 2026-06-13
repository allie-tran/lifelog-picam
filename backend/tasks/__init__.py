from datetime import datetime, timedelta, timezone
from sqlalchemy import create_engine, delete, insert, or_, select, update
from sqlalchemy.orm import Session
from auth.ortho import get_matrix
from auth.types import Person
from tasks.celery_app import celery
from collections import Counter
from database.models import (
    Device, DeviceWhitelistEmbedding, DeviceWhitelistEntry,
    Image, ImageEmbedding, ImageGPS, ImageObject, ImagePerson, PeopleCluster, Location, RawGPS,
)
from services.anonymise import anonymise_image
from services.describe_segments import describe_segment, simple_describe_segment
from pymongo import MongoClient
import logging
import uuid
import numpy as np

from services.object_detection import ModelWrapper, extract_object_from_images
from location.gps_pipeline import run_pipeline
from routers.explore import _FACES_CACHE
import os
from core.config import _FACE_CLUSTER_THRESHOLD, _FACE_SIMILARITY_THRESHOLD, DIR, THUMBNAIL_DIR

_MAX_CLUSTER_AGE_DAYS = 1

logging.info("Starting Celery worker for describe_segment_task...")
PG_URI = os.getenv("PG_URI", "postgresql://postgres:password@localhost:5432/picam")
engine = create_engine(PG_URI)


_ANONYMOUS_FACE_LABELS = {"redacted face", "face", "Unknown", "unknown", None, ""}

def _build_segment_context(session, device: str, date: str, segment_id: int) -> str:
    try:
        rows = session.execute(
            select(Image.timestamp, Image.local_timestamp, Image.location_id)
            .where(
                Image.device == device,
                Image.date == date,
                Image.segment_id == segment_id,
                Image.deleted == False,
            )
            .order_by(Image.timestamp.asc())
        ).all()

        if not rows:
            return ""

        first_ts = rows[0].local_timestamp or rows[0].timestamp
        last_ts = rows[-1].local_timestamp or rows[-1].timestamp
        duration_min = max(1, int((last_ts - first_ts).total_seconds() / 60))

        day_name = first_ts.strftime("%A")
        date_str = first_ts.strftime("%-d %B %Y")
        time_range = f"{first_ts.strftime('%H:%M')}–{last_ts.strftime('%H:%M')}"
        hour = first_ts.hour
        if hour < 6:
            time_of_day = "night"
        elif hour < 12:
            time_of_day = "morning"
        elif hour < 17:
            time_of_day = "afternoon"
        elif hour < 21:
            time_of_day = "evening"
        else:
            time_of_day = "night"

        lines = [
            f"Date: {day_name}, {date_str}",
            f"Time: {time_of_day}, {time_range} ({duration_min} min)",
        ]

        loc_ids = [r.location_id for r in rows if r.location_id]
        if loc_ids:
            most_common_id = Counter(loc_ids).most_common(1)[0][0]
            loc = session.execute(
                select(Location).where(Location.id == most_common_id)
            ).scalars().first()
            if loc:
                place = loc.name or loc.suburb or ""
                city = loc.city or ""
                country = loc.country or ""
                parts = list(dict.fromkeys(p for p in [place, city, country] if p))
                loc_str = ", ".join(parts)
                movement = "in transit" if loc.stop is False else "stationary"
                lines.append(f"Location: {movement} — {loc_str}" if loc_str else f"Location: {movement}")

        face_labels = session.execute(
            select(ImagePerson.label)
            .join(Image, Image.id == ImagePerson.image_id)
            .where(
                Image.device == device,
                Image.date == date,
                Image.segment_id == segment_id,
                Image.deleted == False,
                ImagePerson.label.notin_(list(_ANONYMOUS_FACE_LABELS - {None, ""})),
                ImagePerson.label.isnot(None),
                ImagePerson.label != "",
            )
        ).scalars().all()
        named_people = sorted(set(face_labels))
        if named_people:
            lines.append(f"People visible: {', '.join(named_people)}")

        return "\n".join(f"- {l}" for l in lines)
    except Exception as e:
        logging.warning("_build_segment_context failed for %s/%s seg %s: %s", device, date, segment_id, e)
        return ""


@celery.task(name="tasks.describe_segment_task", bind=True)
def describe_segment_task(
    self,
    device, date, thumbnail_paths, segment_id, extra_info: list[str] = []
):
    mongo_client = MongoClient("mongodb://localhost:27017/")

    # Read phase — get context, then release the connection
    with Session(engine) as session:
        context = _build_segment_context(session, device, date, segment_id)

    # LLM call — no DB connection held
    try:
        activity_obj = describe_segment(
            device,
            date,
            thumbnail_paths,
            segment_id=segment_id,
            context=context,
            extra_info=extra_info,
        )

        # Write phase — short transaction
        with Session(engine) as session:
            stmt = update(Image).where(
                Image.device == device,
                Image.segment_id == segment_id,
                Image.date == date,
            ).values(
                activity=activity_obj["activity"],
                activity_group=activity_obj.get("activity_group"),
                activity_description=activity_obj["activity_description"],
                activity_confidence=activity_obj["activity_confidence"],
                activity_tags=activity_obj.get("activity_tags"),
            )
            pg_result = session.execute(stmt)
            logging.info(
                "Updated %d rows for segment %s with activity '%s'",
                pg_result.rowcount, segment_id, activity_obj["activity"],  # type: ignore
            )
            session.commit()

            try:
                from database.models import Image as _Img
                from services.notify import maybe_notify_segment
                img_row = session.execute(
                    select(_Img.location_id, _Img.thumbnail)
                    .where(_Img.device == device, _Img.segment_id == segment_id, _Img.date == date)
                    .order_by(_Img.timestamp.asc())
                    .limit(1)
                ).first()
                maybe_notify_segment(
                    session, device, date, segment_id,
                    activity_obj["activity"],
                    img_row.location_id if img_row else None,
                    img_row.thumbnail if img_row else None,
                )
                session.commit()
            except Exception as _ne:
                logging.warning("maybe_notify_segment failed for %s/%s seg %s: %s", device, date, segment_id, _ne)

        # Bust browse + day-nav cache (no DB connection needed)
        from integrations.sessions.redis import redis_client as _rc
        _rc.delete_pattern(f"browse:{device}:{date}:*")
        _rc.delete_value(f"day-nav:{device}:{date}")

        # Mark day summary dirty in MongoDB
        mongo_client["picam"]["day_summaries"].update_one(
            {"date": date, "device": device},
            {
                "$addToSet": {"dirty_segment_ids": segment_id},
                "$set": {"text_summary_stale": True, "updated": True},
            },
            upsert=True,
        )
    except Exception as e:
        logging.error("Error describing segment %s for %s on %s: %s", segment_id, device, date, e)


@celery.task(name="tasks.resync_day_task", bind=True)
def resync_day_task(self, device: str, date: str):
    from services.segmentation import segment_images
    from services.utils import compress_image

    mongo_client = MongoClient("mongodb://localhost:27017/")

    # Step 1: rerun GPS pipeline so location_id is fresh before resegmentation
    with Session(engine) as session:
        try:
            run_pipeline(session, device, date)
            logging.info("resync_day: GPS pipeline done for %s/%s", device, date)
        except Exception as e:
            logging.warning("resync_day: GPS pipeline failed for %s/%s: %s", device, date, e)

    with Session(engine) as session:
        # Step 2: fetch all images ordered by timestamp
        all_images = session.execute(
            select(Image.id, Image.image_path, Image.segment_id, Image.activity)
            .where(
                Image.device == device,
                Image.date == date,
                Image.deleted == False,
            )
            .order_by(Image.timestamp.asc())
        ).all()

        if not all_images:
            logging.info("resync_day: no images for %s/%s", device, date)
            return

        all_paths = [img.image_path for img in all_images]
        path_to_img = {img.image_path: img for img in all_images}

        # Step 3: compute new segmentation without saving
        new_segments = segment_images(session, device, all_paths)
        if not new_segments:
            logging.warning("resync_day: segmentation returned nothing for %s/%s, aborting", device, date)
            return

        # Step 4: build old segment identity as (first_path, last_path) per segment,
        # where paths are in timestamp order (all_images is already ordered by timestamp)
        sid_to_ordered_paths: dict[int, list[str]] = {}
        for img in all_images:
            if img.segment_id is not None:
                sid_to_ordered_paths.setdefault(img.segment_id, []).append(img.image_path)

        old_bounds: set[tuple[str, str]] = {
            (paths[0], paths[-1])
            for paths in sid_to_ordered_paths.values()
            if paths
        }

        # Step 5: mark images in new segments that don't align with any old segment
        # for activity erasure — a segment "aligns" iff its first and last image match
        cleared_ids: set[int] = set()
        for new_seg_paths in new_segments:
            if not new_seg_paths:
                continue
            if (new_seg_paths[0], new_seg_paths[-1]) not in old_bounds:
                cleared_ids.update(
                    path_to_img[p].id for p in new_seg_paths if p in path_to_img
                )

        if cleared_ids:
            session.execute(
                update(Image)
                .where(Image.id.in_(list(cleared_ids)))
                .values(
                    activity=None, activity_group=None, activity_description=None,
                    activity_confidence=None, activity_tags=None,
                )
            )
            logging.info(
                "resync_day: cleared activity on %d images for %s/%s", len(cleared_ids), device, date
            )

        # Step 6: assign new segment IDs — sequential starting from 1,
        # in the order segment_images returned them (chronological)
        for new_sid, new_seg_paths in enumerate(new_segments, start=1):
            if not new_seg_paths:
                continue
            session.execute(
                update(Image)
                .where(
                    Image.image_path.in_(new_seg_paths),
                    Image.device == device,
                    Image.date == date,
                )
                .values(segment_id=new_sid)
            )

        session.commit()
        logging.info("resync_day: assigned %d segments for %s/%s", len(new_segments), device, date)

        # Step 7: dispatch LLM for segments with unannotated images
        for new_sid, new_seg_paths in enumerate(new_segments, start=1):
            if not new_seg_paths:
                continue
            needs_annotation = any(
                path_to_img[p].id in cleared_ids
                or not path_to_img[p].activity
                or path_to_img[p].activity == ""
                for p in new_seg_paths
                if p in path_to_img
            )
            if needs_annotation:
                compressed = [compress_image(f"{device}/{p}") for p in new_seg_paths[:20]]
                describe_segment_task.delay(device, date, compressed, new_sid)
                logging.info("resync_day: queued LLM for segment %d", new_sid)

    mongo_client["picam"]["day_summaries"].update_one(
        {"date": date, "device": device},
        {"$set": {"processing": True, "dirty_segment_ids": [], "text_summary_stale": True}},
        upsert=True,
    )
    mongo_client.close()

    from tasks.day_summary import _day_summary_bg, DEFAULT_TARGETS
    target_dicts = [
        {"name": t.name, "action_type": t.action_type.value, "query_prompt": t.query_prompt}
        for t in DEFAULT_TARGETS
    ]
    _day_summary_bg(device, date, target_dicts)

@celery.task(name="tasks.schedule_resync_day_task", bind=True)
def schedule_resync_day_task(self):
    with Session(engine) as session:
        today = datetime.now().date()
        devices = session.execute(
            select(Image.device)
            .where(Image.date == today)
            .distinct()
        ).scalars().all()
        for device in devices:
            resync_day_task.delay(device, today.isoformat())
            logging.info("Scheduled resync_day_task for device %s on %s", device, today.isoformat())

@celery.task(name="tasks.yolo_process_images_task", bind=True)
def yolo_process_images_task(
    self,
    device,
    paths,
    whitelist_names: list[str] = [],
    whitelist_embeddings: list[list[list[float]]] = [],
    whitelist_cluster_ids: list[str] = [],
):
    logging.info("Starting YOLO processing for device %s with %d images", device, len(paths))
    if not paths:
        return

    whitelist = [
        Person(name=name, embeddings=embedding, cropped=[""], cluster_id=cluster_id)
        for name, embedding, cluster_id in zip(whitelist_names, whitelist_embeddings, whitelist_cluster_ids)
    ]

    # Heavy inference — no DB connection held
    results = extract_object_from_images(paths, whitelist)
    logging.info("Completed YOLO processing for device %s, got results for %d images", device, len(results))

    # Write phase — short transaction
    relative_paths = [path.split(f"{device}/")[1] for path in paths]
    with Session(engine) as session:
        pg_results = session.execute(
            select(Image.id, Image.image_path).where(
                Image.device == device, Image.image_path.in_(relative_paths)
            )
        ).fetchall()
        image_id_map = {r.image_path: r.id for r in pg_results}

        object_rows = []
        person_rows = []
        image_rows = []
        # Collect boxes per image for anonymise dispatch after YOLO write
        image_boxes: dict[str, tuple[list, list]] = {}
        for r in results:
            image_path = r["image_path"]
            relative_path = image_path.split(f"{device}/")[1]
            if image_id_map.get(relative_path) is None:
                continue
            image_id = image_id_map[relative_path]

            for obj in r["objects"]:
                obj = obj.model_dump()
                object_rows.append({
                    "image_id": image_id,
                    "label": obj["label"],
                    "confidence": obj["confidence"],
                    "bbox": obj["bbox"],
                    "rel_bbox": obj["rel_bbox"],
                })

            blur_boxes = []
            wl_boxes = []
            for person in r["people"]:
                person = person.model_dump()
                person_rows.append({
                    "image_id": image_id,
                    "label": person["label"],
                    "confidence": person["confidence"],
                    "bbox": person["bbox"],
                    "rel_bbox": person["rel_bbox"],
                    "embedding": person["embedding"],
                    "embedding_created_at": datetime.now(timezone.utc),
                    "cluster_id": person["cluster_id"],
                })
                if person["label"] in ("redacted face", "face"):
                    blur_boxes.append(person["bbox"])
                else:
                    wl_boxes.append(person["bbox"])
            image_boxes[relative_path] = (blur_boxes, wl_boxes)
            image_rows.append(image_id)

        affected_ids = list(image_id_map.values())
        if affected_ids:
            session.execute(delete(ImageObject).where(ImageObject.image_id.in_(affected_ids)))
            session.execute(delete(ImagePerson).where(ImagePerson.image_id.in_(affected_ids)))

        if object_rows:
            session.execute(insert(ImageObject).values(object_rows))
            logging.info("Inserted %d objects", len(object_rows))

        if person_rows:
            session.execute(insert(ImagePerson).values(person_rows))
            logging.info("Inserted %d people", len(person_rows))

        # Mark images as processed by YOLO/InsightFace (but not DeepFace, which is separate)
        session.execute(
            update(Image)
            .where(Image.id.in_(image_rows))
            .values(proc_yolo=True, proc_insightface=True, proc_deepface=False)
        )
        logging.info("Updated %d images as YOLO/InsightFace processed", len(image_rows))
        session.commit()
        session.flush()

    # Anonymise inline — boxes are in memory so no DB round-trip needed, and
    # running inline keeps the queue shallow (no N individual tasks queued here).
    thumbnail_updates: list[tuple[str, str]] = []  # (rel_path, thumb_rel)
    for rel_path, (blur_boxes, wl_boxes) in image_boxes.items():
        thumb_rel = f"{rel_path.rsplit('.', 1)[0]}.webp"
        thumb_path = f"{THUMBNAIL_DIR}/{device}/{thumb_rel}"
        if not os.path.exists(thumb_path):
            path = f"{DIR}/{device}/{rel_path}"
            try:
                anonymise_image(path, thumb_path, blur_boxes, wl_boxes)
                logging.info("Anonymised %s/%s", device, rel_path)
                thumbnail_updates.append((rel_path, thumb_rel))
            except Exception as exc:
                logging.warning("Anonymise failed for %s/%s: %s", device, rel_path, exc)
        else:
            thumbnail_updates.append((rel_path, thumb_rel))

    if thumbnail_updates:
        with Session(engine) as session:
            for rel_path, thumb_rel in thumbnail_updates:
                session.execute(
                    update(Image)
                    .where(Image.device == device, Image.image_path == rel_path)
                    .values(thumbnail=thumb_rel)
                )
            session.commit()

    recluster_unassigned_faces_task.delay(device)


@celery.task(name="tasks.update_location_task", bind=True)
def update_location_task(self, device: str, date: str):
    try:
        with Session(engine) as session:
            run_pipeline(session, device, date)
        logging.info("Location pipeline complete for %s/%s", device, date)
    except Exception as e:
        logging.error("update_location_task failed for %s/%s: %s", device, date, e)


@celery.task(name="tasks.recluster_unassigned_faces_task", bind=True)
def recluster_unassigned_faces_task(self, device: str):
    with Session(engine) as session:
        device_row = session.execute(
            select(Device).where(Device.device_id == device)
        ).scalar()
        keep = device_row.keep_face_recognition if device_row else False

    if keep:
        _recluster_whitelist_mode(device)
    else:
        _recluster_clustering_mode(device)


def _recluster_clustering_mode(device: str):
    # --- Read phase (short session) ---
    with Session(engine) as session:
        rows = session.execute(
            select(ImagePerson.id, ImagePerson.embedding)
            .join(Image, Image.id == ImagePerson.image_id)
            .where(
                Image.device == device,
                ImagePerson.cluster_id.is_(None),
                ImagePerson.embedding.isnot(None),
            )
        ).all()

        clusters = session.execute(
            select(PeopleCluster.id, PeopleCluster.center_embedding)
            .where(or_(PeopleCluster.device == device, PeopleCluster.device.is_(None)))
        ).all()

    if not rows:
        return

    # --- Numpy phase (no DB connection) ---
    person_ids = [r.id for r in rows]
    person_embs = np.array([np.array(r.embedding, dtype=np.float32) for r in rows])
    person_embs /= np.linalg.norm(person_embs, axis=1, keepdims=True) + 1e-8

    if clusters:
        centroid_ids = [c.id for c in clusters]
        centroid_matrix = np.array(
            [np.array(c.center_embedding, dtype=np.float32) for c in clusters]
        )
        centroid_matrix /= np.linalg.norm(centroid_matrix, axis=1, keepdims=True) + 1e-8
        cluster_counts = {c.id: 1 for c in clusters}
    else:
        centroid_ids = []
        centroid_matrix = np.empty((0, 512), dtype=np.float32)
        cluster_counts = {}

    person_cluster_map: dict[uuid.UUID, uuid.UUID] = {}
    centroid_updates: dict[uuid.UUID, list] = {}
    new_cluster_rows: list[dict] = []
    assigned = created = 0

    for person_id, emb_norm in zip(person_ids, person_embs):
        if len(centroid_ids) > 0:
            distances = 1.0 - (centroid_matrix @ emb_norm)
            best_idx = int(np.argmin(distances))
            best_dist = float(distances[best_idx])
        else:
            best_dist = 1.0
            best_idx = -1

        if best_dist < _FACE_CLUSTER_THRESHOLD:
            cluster_id = centroid_ids[best_idx]
            n = cluster_counts[cluster_id]
            new_centroid = (centroid_matrix[best_idx] * n + emb_norm) / (n + 1)
            new_centroid /= np.linalg.norm(new_centroid) + 1e-8
            centroid_matrix[best_idx] = new_centroid
            cluster_counts[cluster_id] += 1
            centroid_updates[cluster_id] = new_centroid.tolist()
            person_cluster_map[person_id] = cluster_id
            assigned += 1
        else:
            new_id = uuid.uuid4()
            new_cluster_rows.append({
                "id": new_id,
                "cluster_label": "Unknown",
                "center_embedding": emb_norm.tolist(),
                "device": device,
                "whitelist_entry_id": None,
            })
            centroid_ids.append(new_id)
            centroid_matrix = np.vstack([centroid_matrix, emb_norm[np.newaxis, :]])
            cluster_counts[new_id] = 1
            person_cluster_map[person_id] = new_id
            created += 1

    # --- Write phase (short session) ---
    with Session(engine) as session:
        if new_cluster_rows:
            session.execute(insert(PeopleCluster).values(new_cluster_rows))

        for cluster_id, new_centroid in centroid_updates.items():
            session.execute(
                update(PeopleCluster)
                .where(PeopleCluster.id == cluster_id)
                .values(center_embedding=new_centroid)
            )

        # Bulk update: group person IDs by their assigned cluster
        by_cluster: dict[uuid.UUID, list] = {}
        for pid, cid in person_cluster_map.items():
            by_cluster.setdefault(cid, []).append(pid)
        for cluster_id, pids in by_cluster.items():
            session.execute(
                update(ImagePerson)
                .where(ImagePerson.id.in_(pids))
                .values(cluster_id=cluster_id)
            )

        session.commit()

    _FACES_CACHE.pop(device, None)
    logging.info("Face re-cluster (clustering mode) %s: %d assigned, %d new", device, assigned, created)


def _recluster_whitelist_mode(device: str, days_back: int = 90):
    # --- Read phase (short session) ---
    with Session(engine) as session:
        rows = session.execute(
            select(ImagePerson.id, ImagePerson.embedding)
            .join(Image, Image.id == ImagePerson.image_id)
            .where(
                Image.device == device,
                Image.timestamp >= datetime.now(timezone.utc) - timedelta(days=days_back),
                ImagePerson.cluster_id.is_(None),
                ImagePerson.embedding.isnot(None),
            )
        ).all()

        clusters = session.execute(
            select(PeopleCluster.id, PeopleCluster.cluster_label, PeopleCluster.center_embedding)
            .where(
                PeopleCluster.device == device,
                PeopleCluster.whitelist_entry_id.isnot(None),
            )
        ).all()

    if not rows:
        return

    if not clusters:
        logging.debug("No whitelist clusters for device %s; skipping assignment", device)
        delete_unknown_face_embeddings_task.delay(device)
        return

    # --- Numpy phase (no DB connection) ---
    person_ids = [r.id for r in rows]
    person_embs = np.array([np.array(r.embedding, dtype=np.float32) for r in rows])
    person_embs /= np.linalg.norm(person_embs, axis=1, keepdims=True) + 1e-8

    centroid_ids = [c.id for c in clusters]
    cluster_labels = {c.id: c.cluster_label for c in clusters}
    centroid_matrix = np.array(
        [np.array(c.center_embedding, dtype=np.float32) for c in clusters]
    )
    centroid_matrix /= np.linalg.norm(centroid_matrix, axis=1, keepdims=True) + 1e-8

    # cluster_id -> (person_ids, label)
    by_cluster: dict[uuid.UUID, tuple[list, str]] = {}
    assigned = 0

    for person_id, emb_norm in zip(person_ids, person_embs):
        distances = 1.0 - (centroid_matrix @ emb_norm)
        best_idx = int(np.argmin(distances))
        if float(distances[best_idx]) < _FACE_CLUSTER_THRESHOLD:
            cluster_id = centroid_ids[best_idx]
            label = cluster_labels[cluster_id]
            if cluster_id not in by_cluster:
                by_cluster[cluster_id] = ([], label)
            by_cluster[cluster_id][0].append(person_id)
            assigned += 1

    # --- Write phase (short session) ---
    if by_cluster:
        with Session(engine) as session:
            for cluster_id, (pids, label) in by_cluster.items():
                session.execute(
                    update(ImagePerson)
                    .where(ImagePerson.id.in_(pids))
                    .values(cluster_id=cluster_id, label=label)
                )
            session.commit()

    _FACES_CACHE.pop(device, None)
    delete_unknown_face_embeddings_task.delay(device)
    logging.info("Face re-cluster (whitelist mode) %s: %d assigned to whitelist", device, assigned)


_FACE_EMBEDDING_TTL_MINUTES = 30

def _non_whitelisted_condition(device: str | None = None):
    """SQLAlchemy condition: face is not assigned to a whitelisted cluster."""
    wl_cluster_ids = select(PeopleCluster.id).where(
        PeopleCluster.whitelist_entry_id.isnot(None),
        *([PeopleCluster.device == device] if device else []),
    )
    return or_(
        ImagePerson.cluster_id.is_(None),
        ImagePerson.cluster_id.notin_(wl_cluster_ids),
    )


@celery.task(name="tasks.delete_unknown_face_embeddings_task")
def delete_unknown_face_embeddings_task(device: str):
    """Delete non-whitelisted face records older than the TTL for one device."""
    threshold = datetime.now(timezone.utc) - timedelta(minutes=_FACE_EMBEDDING_TTL_MINUTES)
    with Session(engine) as session:
        result = session.execute(
            update(ImagePerson)
            .where(
                ImagePerson.image_id.in_(select(Image.id).where(Image.device == device)),
                ImagePerson.embedding_created_at.isnot(None),
                ImagePerson.embedding_created_at < threshold,
                _non_whitelisted_condition(device),
            )
            .values(embedding=None, cluster_id=None, label=None)
        )
        session.commit()

    logging.info("Deleted %d expired face records for device %s", result.rowcount, device)  # type: ignore

@celery.task(name="tasks.purge_expired_face_embeddings_task")
def purge_expired_face_embeddings_task():
    """Global 5-minute TTL enforcement: delete all non-whitelisted face records older than 30 min."""
    with Session(engine) as session:
        devices = session.execute(select(Device.device_id).where(Device.keep_face_recognition == True)).scalars().all()
        for device in devices:
            delete_unknown_face_embeddings_task.delay(device)  # Schedule per-device cleanup

# ---------------------------------------------------------------------------
# Cluster rebuild tasks (triggered when toggling recognition mode)
# ---------------------------------------------------------------------------
def _kmeans_numpy(embeddings: np.ndarray, k: int, max_iter: int = 100):
    """Spherical KMeans on L2-normalised embeddings using cosine distance."""
    n = embeddings.shape[0]
    rng = np.random.default_rng(42)
    centers = embeddings[rng.choice(n, k, replace=False)].copy()

    labels = np.zeros(n, dtype=np.int32)
    for _ in range(max_iter):
        sims = embeddings @ centers.T
        new_labels = np.argmax(sims, axis=1).astype(np.int32)

        new_centers = np.zeros_like(centers)
        for j in range(k):
            mask = new_labels == j
            if mask.any():
                c = embeddings[mask].mean(axis=0)
                norm = np.linalg.norm(c)
                new_centers[j] = c / (norm + 1e-8)
            else:
                new_centers[j] = centers[j]

        if np.array_equal(new_labels, labels):
            break
        labels = new_labels
        centers = new_centers

    return labels, centers


@celery.task(name="tasks.setup_clustering_task", bind=True)
def setup_clustering_task(self, device: str, n_clusters: int = 20):
    # --- Read phase ---
    with Session(engine) as session:
        rows = session.execute(
            select(ImagePerson.id, ImagePerson.embedding)
            .join(Image, Image.id == ImagePerson.image_id)
            .where(Image.device == device, ImagePerson.embedding.isnot(None)
        )).all()

    if not rows:
        logging.info("setup_clustering_task: no face embeddings for device %s", device)
        return

    # --- KMeans phase (no DB connection) ---
    ids = [r.id for r in rows]
    raw = np.array([np.array(r.embedding, dtype=np.float32) for r in rows])
    embeddings = raw / (np.linalg.norm(raw, axis=1, keepdims=True) + 1e-8)

    k = min(n_clusters, len(ids))
    labels, centers = _kmeans_numpy(embeddings, k)

    # Build cluster rows and person assignments
    cluster_map: dict[int, uuid.UUID] = {}
    cluster_rows = []
    for label_idx in range(k):
        new_id = uuid.uuid4()
        cluster_rows.append({
            "id": new_id,
            "cluster_label": f"Person {label_idx + 1}",
            "center_embedding": centers[label_idx].tolist(),
            "device": device,
            "whitelist_entry_id": None,
        })
        cluster_map[label_idx] = new_id

    by_cluster: dict[int, list] = {}
    for person_id, label in zip(ids, labels.tolist()):
        by_cluster.setdefault(label, []).append(person_id)

    # --- Write phase (short session) ---
    with Session(engine) as session:
        if cluster_rows:
            session.execute(insert(PeopleCluster).values(cluster_rows))
        for label_idx, pids in by_cluster.items():
            session.execute(
                update(ImagePerson)
                .where(ImagePerson.id.in_(pids))
                .values(cluster_id=cluster_map[label_idx])
            )
        session.commit()

    _FACES_CACHE.pop(device, None)
    logging.info("setup_clustering_task: created %d clusters for device %s", k, device)


@celery.task(name="tasks.setup_whitelist_clusters_task", bind=True)
def setup_whitelist_clusters_task(self, device: str):
    # --- Read phase ---
    with Session(engine) as session:
        device_row = session.execute(
            select(Device).where(Device.device_id == device)
        ).scalar()
        if not device_row:
            return

        entries = session.execute(
            select(DeviceWhitelistEntry).where(DeviceWhitelistEntry.device_id == device_row.id)
        ).scalars().all()

        if not entries:
            logging.info("setup_whitelist_clusters_task: no whitelist entries for device %s", device)
            return

        # Load embeddings for each entry while session is open
        entry_data = []
        for entry in entries:
            emb_rows = session.execute(
                select(DeviceWhitelistEmbedding.embedding)
                .where(DeviceWhitelistEmbedding.entry_id == entry.id)
            ).scalars().all()
            entry_data.append((str(entry.name), entry.id, emb_rows))

    # --- Compute centroids (no DB) ---
    cluster_rows = []
    entries_with_data = []
    for name, entry_id, emb_rows in entry_data:
        if not emb_rows:
            continue
        mat = np.array([np.array(e, dtype=np.float32) for e in emb_rows])
        center = mat.mean(axis=0)
        norm = np.linalg.norm(center)
        if norm > 1e-8:
            center /= norm
        cluster_rows.append({
            "id": uuid.uuid4(),
            "cluster_label": name,
            "center_embedding": center.tolist(),
            "device": device,
            "whitelist_entry_id": entry_id,
        })
        entries_with_data.append((name, entry_id, emb_rows))

    # --- Write clusters (short session) ---
    if cluster_rows:
        with Session(engine) as session:
            session.execute(insert(PeopleCluster).values(cluster_rows))
            session.commit()
        logging.info(
            "setup_whitelist_clusters_task: created %d whitelist clusters for device %s",
            len(cluster_rows), device,
        )

    # Assign all unassigned faces to the new clusters
    _recluster_whitelist_mode(device, days_back=_MAX_CLUSTER_AGE_DAYS)

    # Queue per-entry relabeling for the past 24h
    for name, entry_id, emb_rows in entries_with_data:
        embeddings = [list(map(float, e)) for e in emb_rows]
        relabel_whitelist_faces_task.apply_async(
            args=(device, name, embeddings),
            kwargs={"since_hours": 24},
            retry=False,
        )

    _FACES_CACHE.pop(device, None)
    logging.info("setup_whitelist_clusters_task: done for device %s", device)


@celery.task(name="tasks.relabel_whitelist_faces_task", bind=True)
def relabel_whitelist_faces_task(
    self,
    device: str,
    name: str,
    new_embeddings: list[list[float]],
    threshold: float = _FACE_SIMILARITY_THRESHOLD,
    since_hours: int | None = None,
):
    from core.config import DIR, THUMBNAIL_DIR

    new_embs = [np.array(e, dtype=np.float32) for e in new_embeddings]
    new_embs = [e / (np.linalg.norm(e) + 1e-8) for e in new_embs]

    query = (
        select(
            ImagePerson.id, ImagePerson.image_id, ImagePerson.embedding,
            ImagePerson.bbox, Image.image_path, Image.thumbnail,
        )
        .join(Image, Image.id == ImagePerson.image_id)
        .where(
            Image.device == device,
            ImagePerson.label == "redacted face",
            ImagePerson.embedding.isnot(None),
            Image.deleted == False,
        )
    )
    if since_hours is not None:
        since_dt = datetime.now(timezone.utc) - timedelta(hours=since_hours)
        query = query.where(Image.timestamp >= since_dt)

    # --- Read phase ---
    with Session(engine) as session:
        rows = session.execute(query).all()

    # --- Numpy matching phase (no DB) ---
    matched_ids: list[uuid.UUID] = []
    relabelled_image_ids: set = set()

    for row in rows:
        face_emb = np.array(row.embedding, dtype=np.float32)
        norm = np.linalg.norm(face_emb)
        if norm < 1e-8:
            continue
        face_emb /= norm

        best_sim = max(float(np.dot(ne, face_emb)) for ne in new_embs)
        if best_sim >= threshold:
            matched_ids.append(row.id)
            relabelled_image_ids.add(row.image_id)

    # --- Write phase (short session) ---
    if matched_ids:
        with Session(engine) as session:
            session.execute(
                update(ImagePerson)
                .where(ImagePerson.id.in_(matched_ids))
                .values(label=name, confidence=threshold)
            )
            session.commit()

    logging.info(
        "relabel_whitelist: relabelled %d faces as '%s' for device %s",
        len(matched_ids), name, device,
    )

    if not relabelled_image_ids:
        return

    # Fetch image paths for thumbnail re-generation (short session)
    with Session(engine) as session:
        affected_images = session.execute(
            select(Image.id, Image.image_path, Image.thumbnail)
            .where(Image.id.in_(relabelled_image_ids), Image.device == device)
        ).all()

        image_persons = {}
        for img in affected_images:
            persons = session.execute(
                select(ImagePerson.label, ImagePerson.bbox)
                .where(ImagePerson.image_id == img.id)
            ).all()
            image_persons[img.id] = (img.image_path, img.thumbnail, persons)

    # File ops + task dispatch (no DB)
    queued = 0
    for img_id, (image_path, thumbnail, persons) in image_persons.items():
        boxes = [p.bbox for p in persons if p.label in ("redacted face", "face")]
        whitelist_boxes = [p.bbox for p in persons if p.label not in ("redacted face", "face")]

        src = f"{DIR}/{device}/{image_path}"
        thumb = f"{THUMBNAIL_DIR}/{device}/{thumbnail}"

        if not os.path.exists(src):
            continue

        try:
            if os.path.exists(thumb):
                os.remove(thumb)
        except OSError:
            pass

        anonymise_image_task.delay(device, image_path, thumb, boxes, whitelist_boxes, skip_sam3=True)
        queued += 1

    logging.info(
        "relabel_whitelist: re-queued thumbnails for %d images on device %s",
        queued, device,
    )


@celery.task(name="tasks.anonymise_image_task", bind=True)
def anonymise_image_task(
    self,
    device_id,
    relative_path,
    thumbnail_path,
    blur_face_boxes=None,
    whitelist_boxes=None,
    skip_sam3=False,
):
    # If boxes weren't passed in (e.g. catchup path), fetch them from DB.
    # No polling — caller is responsible for dispatching after YOLO is done.
    if blur_face_boxes is None or whitelist_boxes is None:
        with Session(engine) as session:
            img = session.execute(
                select(Image).where(Image.image_path == relative_path, Image.device == device_id)
            ).scalars().first()
            if img:
                res = session.execute(
                    select(ImagePerson).where(ImagePerson.image_id == img.id)
                ).scalars().all()
                blur_face_boxes = [p.bbox for p in res if p.label in ("redacted face", "face")]
                whitelist_boxes = [p.bbox for p in res if p.label not in ("redacted face", "face")]
            else:
                blur_face_boxes = []
                whitelist_boxes = []

    logging.info(
        "Anonymising %s/%s: %d faces to blur, %d whitelisted",
        device_id, relative_path, len(blur_face_boxes), len(whitelist_boxes),
    )
    path = f"{DIR}/{device_id}/{relative_path}"
    anonymise_image(path, thumbnail_path, blur_face_boxes, whitelist_boxes, skip_sam3=skip_sam3)

    with Session(engine) as session:
        session.execute(
            update(Image)
            .where(Image.image_path == relative_path, Image.device == device_id)
            .values(thumbnail=thumbnail_path)
        )
        session.commit()

    return thumbnail_path


@celery.task(name="tasks.compute_bio_day_stats_task", bind=True)
def compute_bio_day_stats_task(self, device_id: str, date: str):
    from services.bio_stats import compute_and_upsert_bio_day_stats
    try:
        with Session(engine) as session:
            result = compute_and_upsert_bio_day_stats(session, device_id, date)
        if result:
            logging.info("Computed bio_day_stats for %s/%s", device_id, date)
        else:
            logging.debug("No bio data for %s/%s, skipped.", device_id, date)
    except Exception as e:
        logging.error("compute_bio_day_stats_task failed for %s/%s: %s", device_id, date, e)




@celery.task(name="tasks.nightly_recluster_all_devices")
def nightly_recluster_all_devices():
    # Only whitelist-mode devices retain face embeddings beyond the 30-min TTL,
    # so reclustering is only meaningful for them.
    with Session(engine) as session:
        device_ids = session.execute(
            select(Device.device_id).where(Device.keep_face_recognition == True)
        ).scalars().all()

    for device_id in device_ids:
        recluster_unassigned_faces_task.delay(device_id)
    logging.info("Queued nightly face re-cluster for %d whitelist-mode devices.", len(device_ids))


@celery.task(name="tasks.nightly_bio_stats_all_devices")
def nightly_bio_stats_all_devices():
    from database.models import SensorDevice

    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    yesterday = (datetime.now(timezone.utc) - timedelta(days=1)).strftime("%Y-%m-%d")

    with Session(engine) as session:
        device_ids = session.execute(
            select(SensorDevice.device_id)
        ).scalars().all()

    for device_id in device_ids:
        for date in (today, yesterday):
            compute_bio_day_stats_task.delay(device_id, date)

    logging.info("Queued nightly bio_day_stats for %d devices.", len(device_ids))

@celery.task(name="tasks.location_update_all_devices")
def location_update_all_devices():
    from sqlalchemy import func
    import sqlalchemy as sa

    with Session(engine) as session:
        # Subquery: device UUIDs that have any RawGPS record on a given date
        raw_gps_dates = (
            select(Device.device_id.label("dev_str"), func.date(RawGPS.timestamp).label("gps_date"))
            .join(RawGPS, RawGPS.device_id == Device.id)
            .subquery()
        )

        rows = session.execute(
            select(Image.device, Image.date)
            .outerjoin(ImageGPS, ImageGPS.image_id == Image.id)
            .join(raw_gps_dates, sa.and_(
                raw_gps_dates.c.dev_str == Image.device,
                sa.cast(raw_gps_dates.c.gps_date, sa.Text) == Image.date,
            ))
            .where(
                Image.location_id.is_(None),
                Image.deleted == False,
                ImageGPS.image_id.is_(None),
            )
            .distinct()
            .order_by(Image.date.desc())
        ).all()

    for device, date in rows:
        update_location_task.delay(device, date)
    logging.info("Queued nightly location updates for %d device/date pairs.", len(rows))


@celery.task(name="tasks.pipeline_catchup_task")
def pipeline_catchup_task():
    from collections import defaultdict as _defaultdict
    logging.info("Starting pipeline catch-up task: checking for unprocessed images...")

    cutoff = datetime.now(timezone.utc) - timedelta(hours=2)
    past_cutoff = datetime.now(timezone.utc) - timedelta(days=7)
    queued_yolo = queued_thumbs = queued_enc = queued_seg = 0

    # --- Phase 1: YOLO backlog — own session, closed before dispatch ---
    yolo_by_device: dict[str, list[str]] = _defaultdict(list)
    with Session(engine) as session:
        for device, path in session.execute(
            select(Image.device, Image.image_path)
            .where(
                Image.proc_yolo == False,
                Image.timestamp < cutoff,
                Image.timestamp > past_cutoff,
                Image.deleted == False,
                Image.is_video == False,
            )
            .order_by(Image.timestamp.asc())
            .limit(100)
        ).all():
            yolo_by_device[device].append(f"{DIR}/{device}/{path}")

    for device, full_paths in yolo_by_device.items():
        yolo_process_images_task.delay(device, full_paths, [], [])
        queued_yolo += len(full_paths)
    if queued_yolo:
        logging.info("catchup: queued YOLO for %d images across %d devices", queued_yolo, len(yolo_by_device))

    # --- Phase 2: CLIP embeddings — own session per image so inference doesn't hold the pool ---
    with Session(engine) as session:
        no_emb_rows = session.execute(
            select(Image.device, Image.image_path)
            .outerjoin(ImageEmbedding, ImageEmbedding.image_id == Image.id)
            .where(
                ImageEmbedding.image_id.is_(None),
                Image.timestamp < cutoff,
                Image.timestamp > past_cutoff,
                Image.deleted == False,
                Image.is_video == False,
            )
            .order_by(Image.timestamp.asc())
            .limit(50)
        ).all()

    if no_emb_rows:
        from pipelines.all import encode_image as _encode_image
        for device, image_path in no_emb_rows:
            try:
                with Session(engine) as session:
                    _encode_image(session, device, image_path)
                queued_enc += 1
            except Exception as exc:
                logging.warning("catchup: encode failed for %s/%s: %s", device, image_path, exc)

    # --- Phase 3: Missing thumbnails ---
    # Find images where YOLO is done but no thumbnail has been created yet.
    with Session(engine) as session:
        thumb_rows = session.execute(
            select(Image.device, Image.image_path)
            .where(
                Image.proc_yolo == True,
                Image.thumbnail.is_(None),
                Image.timestamp < cutoff,
                Image.timestamp > past_cutoff,
                Image.deleted == False,
                Image.is_video == False,
            )
            .order_by(Image.timestamp.desc())
            .limit(200)
        ).all()

    # Collect images whose source file still exists.
    missing: list[tuple[str, str, str]] = []  # (device, image_path, thumb_path)
    for device, image_path in thumb_rows:
        if not os.path.exists(f"{DIR}/{device}/{image_path}"):
            continue
        thumb_rel = f"{image_path.rsplit('.', 1)[0]}.webp"
        thumb_path = f"{THUMBNAIL_DIR}/{device}/{thumb_rel}"
        missing.append((device, image_path, thumb_path))

    if missing:
        # Load face boxes in one query per device.
        boxes_map: dict[tuple[str, str], tuple[list, list]] = {}
        by_device: dict[str, list[str]] = {}
        for device, image_path, _ in missing:
            by_device.setdefault(device, []).append(image_path)
        for device, paths in by_device.items():
            with Session(engine) as session:
                for img_path, label, bbox in session.execute(
                    select(Image.image_path, ImagePerson.label, ImagePerson.bbox)
                    .outerjoin(ImagePerson, ImagePerson.image_id == Image.id)
                    .where(Image.device == device, Image.image_path.in_(paths))
                ).all():
                    blur_list, wl_list = boxes_map.setdefault((device, img_path), ([], []))
                    if bbox is not None:
                        (blur_list if label in ("redacted face", "face") else wl_list).append(bbox)

        for device, image_path, thumb_path in missing:
            blur_boxes, wl_boxes = boxes_map.get((device, image_path), ([], []))
            try:
                thumb_rel = f"{image_path.rsplit('.', 1)[0]}.webp"
                anonymise_image(f"{DIR}/{device}/{image_path}", thumb_path, blur_boxes, wl_boxes)
                with Session(engine) as session:
                    session.execute(
                        update(Image)
                        .where(Image.device == device, Image.image_path == image_path)
                        .values(thumbnail=thumb_rel)
                    )
                    session.commit()
                queued_thumbs += 1
            except Exception as exc:
                logging.warning("catchup anonymise failed %s/%s: %s", device, image_path, exc)
    logging.info("catchup: created %d thumbnails inline", queued_thumbs)

    # --- Phase 4: Unannotated segments — own session, collect then dispatch ---
    seg_dispatch: list[tuple] = []
    with Session(engine) as session:
        for device, date, segment_id in session.execute(
            select(Image.device, Image.date, Image.segment_id)
            .where(
                Image.segment_id.isnot(None),
                or_(Image.activity.is_(None), Image.activity == ""),
                Image.timestamp < cutoff,
                Image.timestamp > past_cutoff,
                Image.deleted == False,
            )
            .group_by(Image.device, Image.date, Image.segment_id)
            .order_by(Image.device, Image.date, Image.segment_id)
            .limit(20)
        ).all():
            seg_paths = session.execute(
                select(Image.image_path)
                .where(
                    Image.device == device,
                    Image.date == date,
                    Image.segment_id == segment_id,
                    Image.deleted == False,
                )
            ).scalars().all()
            if seg_paths:
                thumb_paths = [
                    f"{THUMBNAIL_DIR}/{device}/{p.rsplit('.', 1)[0]}.webp"
                    for p in seg_paths
                ]
                seg_dispatch.append((device, date, segment_id, thumb_paths))

    for device, date, segment_id, thumb_paths in seg_dispatch:
        describe_segment_task.delay(device, date, thumb_paths, segment_id)
        queued_seg += 1

    if queued_yolo or queued_thumbs or queued_enc or queued_seg:
        logging.info(
            "pipeline_catchup: YOLO=%d thumbnails=%d embeddings=%d segments=%d",
            queued_yolo, queued_thumbs, queued_enc, queued_seg,
        )


@celery.task(name="tasks.update_status_summary")
def update_status_summary():
    from database.models import Device as _Device, Image as _Image
    from integrations.sessions.redis import redis_client

    now = datetime.now(timezone.utc)
    cutoff = now - timedelta(hours=2)
    thirty_min_ago = now - timedelta(minutes=30)

    # --- Read phase ---
    with Session(engine) as session:
        active = session.execute(
            select(_Device.device_id)
            .where(_Device.last_seen.isnot(None), _Device.last_seen > cutoff)
        ).scalars().all()

        if not active:
            return

        device_descriptions: dict[str, list[str]] = {}
        for device_id in active:
            rows = session.execute(
                select(_Image.segment_id, _Image.activity_description)
                .where(
                    _Image.device == device_id,
                    _Image.deleted == False,
                    _Image.timestamp > thirty_min_ago,
                    _Image.activity_description.isnot(None),
                    _Image.activity_description != "",
                )
                .distinct(_Image.segment_id)
                .order_by(_Image.segment_id.desc())
                .limit(5)
            ).fetchall()
            descriptions = [r.activity_description for r in rows if r.activity_description]
            if descriptions:
                device_descriptions[device_id] = descriptions

    if not device_descriptions:
        return

    # --- LLM phase (no DB connection) ---
    try:
        from integrations.llm.gemini import LLM
        llm = LLM()
    except Exception as e:
        logging.warning("Status summary: LLM init failed: %s", e)
        return

    for device_id, descriptions in device_descriptions.items():
        try:
            prompt = (
                "You are a lifelogging assistant. Based on these recent activity descriptions "
                "from a wearable camera, write a single concise sentence (under 20 words) "
                "summarising what the person is currently doing. "
                f"Activities (most recent first): {'; '.join(descriptions)}"
            )
            summary_text = llm.generate(prompt)  # type: ignore

            cache_key = f"status:{device_id}:summary"
            redis_client.set_json_with_ttl(
                cache_key,
                {"text": summary_text, "updated_at": now.isoformat()},
                ttl_seconds=25 * 60,
            )
            logging.info("Updated status summary for %s.", device_id)
        except Exception as e:
            logging.error("Status summary failed for %s: %s", device_id, e)

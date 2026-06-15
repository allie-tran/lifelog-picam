from collections import defaultdict
import math
from datetime import datetime, timedelta, timezone
from typing import List, Optional

import numpy as np
from sqlalchemy import and_, select, update
from core.config import SEGMENT_THRESHOLD
from database.models import Image, ImageEmbedding, ImageGPS
from database.types import DaySummaryRecord
from integrations.sessions.redis import RedisClient
from tqdm.auto import tqdm
from services.utils import compress_image
from database.types import _orm_to_lifelog
import logging

logger = logging.getLogger(__name__)
redis_client = RedisClient()

def fetch_embeddings(session, device: str, paths: List[str]) -> tuple[List[str], np.ndarray]:
    records = session.execute(
        select(ImageEmbedding.embedding, Image.image_path).where(
            ImageEmbedding.image_id == Image.id,
            Image.device == device,
            Image.image_path.in_(paths),
        )
    ).all()

    path_to_embedding = {record.image_path: record.embedding for record in records}
    paths = [path for path in paths if path in path_to_embedding]
    embeddings = np.array([path_to_embedding[path] for path in paths])
    return paths, embeddings


def choose_num_thumbnails(
    num_frames: int,
    frames_per_thumb: int = 100,
    min_thumbs: int = 3,
    max_thumbs: int = 8,
) -> int:
    """
    Decide how many thumbnails to show for a segment, based on how many frames it has.

    - Roughly 1 thumbnail per `frames_per_thumb` frames.
    - Always at least `min_thumbs`.
    - Never more than `max_thumbs`.

    Examples with frames_per_thumb=50, max_thumbs=8:
        0 frames   -> 0
        1–100       -> 1
        101–150     -> 2
        ...
        801+       -> 8
    """
    if num_frames <= 0:
        return 0

    estimated = math.ceil(num_frames / frames_per_thumb)
    estimated = max(min_thumbs, estimated)
    estimated = min(max_thumbs, estimated)
    estimated = min(num_frames, estimated)  # can't have more thumbnails than frames
    return estimated

def get_records_for_paths(session, device_id: str, image_paths: List[str]):
    records = session.execute(
        select(Image.image_path, Image.timestamp, Image.location_id, ImageEmbedding.embedding, ImageGPS.mode)
        .join(ImageEmbedding, ImageEmbedding.image_id == Image.id, isouter=True)
        .join(ImageGPS, ImageGPS.image_id == Image.id, isouter=True)
        .where(
            Image.image_path.in_(image_paths),
            Image.device == device_id,
            Image.deleted == False,
        ).order_by(Image.timestamp.asc())
    )
    records = list(records)

    # Split into segments based on time gaps and location changes
    path_to_time = {record.image_path: record.timestamp for record in records}
    path_to_location = {record.image_path: record.location_id for record in records}
    path_to_transport_mode = {record.image_path: record.mode for record in records}
    path_to_embedding = defaultdict(lambda: np.ones(768, dtype=np.float32) * -1)  # default embedding for missing records
    path_to_embedding.update( {record.image_path: record.embedding for record in records if record.embedding is not None} )

    paths = [record.image_path for record in records]
    embeddings = np.array([path_to_embedding[path] for path in paths])

    return paths, embeddings, path_to_time, path_to_location, path_to_transport_mode

def get_boundaries(image_paths: List[str], path_to_time: dict, path_to_location: dict, path_to_transport_mode: dict) -> set:
    time_threshold = timedelta(minutes=5)
    boundaries = set()

    for i in range(1, len(image_paths)):
        img1, img2 = image_paths[i - 1], image_paths[i]
        loc1, loc2 = path_to_location[img1], path_to_location[img2]
        mode1, mode2 = path_to_transport_mode[img1], path_to_transport_mode[img2]
        if loc1 != loc2:
            boundaries.add(image_paths[i])
        # Only split on mode change when both sides have a known mode — a
        # None→value transition (a single missing GPS fix) shouldn't force a
        # boundary; fall through to the time-gap check instead.
        elif mode1 and mode2 and mode1 != mode2:
            boundaries.add(image_paths[i])
        else:
            t1, t2 = path_to_time[img1], path_to_time[img2]
            if abs(t2 - t1) > time_threshold:
                boundaries.add(image_paths[i])
    return boundaries


def segment_images(
    session,
    device_id: str,
    image_paths,
    reverse=False,
) -> list[list[str]]:
    image_paths, features, path_to_time, path_to_location, path_to_transport_mode = get_records_for_paths(session, device_id, image_paths)
    if len(features) == 0:
        return []

    boundaries = get_boundaries(image_paths, path_to_time, path_to_location, path_to_transport_mode)

    # Sort the features and image paths based on the image_pahts
    sorted_indices = np.argsort(image_paths)
    if reverse:
        sorted_indices = sorted_indices[::-1]

    features = features[sorted_indices]
    if len(features) == 0:
        logger.warning("No features found for the given image paths. Segmenting by boundaries only.")
        # just do by boundaries if we don't have enough features
        image_segments = []
        for i, path in enumerate(image_paths):
            if path in boundaries and image_segments:
                image_segments.append([])

            if not image_segments:
                image_segments.append([])

            image_segments[-1].append(path)
        return image_segments

    image_paths = [image_paths[i] for i in sorted_indices]

    # Normalise
    features = features / np.linalg.norm(features, axis=1, keepdims=True)

    # Hearst Textiling
    similarities = [
        np.dot(features[i], features[i - 1]) for i in range(1, len(features))
    ]

    window_size = 3
    if len(similarities) == 0:
        return [image_paths]
    elif len(similarities) < window_size:
        window_size = len(similarities)

    smoothed = np.convolve(
        similarities, np.ones(window_size) / window_size, mode="same"
    )

    depth_scores = []
    for i in range(1, len(smoothed) - 1):
        left_peak = max(smoothed[:i])
        right_peak = max(smoothed[i + 1 :])
        depth = left_peak + right_peak - 2 * smoothed[i]
        depth_scores.append(depth)

    depth_threshold = np.mean(depth_scores) + np.std(depth_scores)
    depth_scores = [0] + depth_scores + [0]  # pad to align with image indices
    k = SEGMENT_THRESHOLD
    logger.info(
        f"Segmenting with depth threshold: {depth_threshold:.4f} and similarity threshold: {k:.4f}"
    )

    # Compare each feature vector with the previous one
    segments: list[list[int]] = []
    current_segment = [0]
    for i in range(1, len(features)):
        similarity = smoothed[i - 1]  # similarity between current and previous
        # Require BOTH a raw drop AND a statistically significant valley — avoids
        # splitting on transient visual changes (lighting, slight camera movement)
        # within the same location/activity.
        if similarity < k and depth_scores[i - 1] > depth_threshold:
            segments.append(current_segment)
            current_segment = [i]
        else:
            current_segment.append(i)

    if current_segment:
        segments.append(current_segment)

    # Merge segments that are too similar
    # Keep boundaries intact, but merge segments on either side if their average features are close enough
    merged_segments = []
    for segment in segments:
        if merged_segments:
            prev_segment = merged_segments[-1]

            prev_feat = np.mean(features[prev_segment], axis=0)
            curr_feat = np.mean(features[segment], axis=0)

            distance = np.linalg.norm(curr_feat - prev_feat)
            if distance < k / 2:
                merged_segments[-1].extend(segment)
                continue

        merged_segments.append(segment)

    # Merge small segments (uses output of the previous merge pass)
    small_merged = []
    min_time = timedelta(minutes=2)
    for segment in merged_segments:
        prev_segment = small_merged[-1] if small_merged else None

        if len(segment) < 3 and small_merged:
            # check the time
            start_image = image_paths[segment[0]]
            end_image = image_paths[small_merged[-1][-1]]
            t1 = path_to_time[start_image]
            t2 = path_to_time[end_image]
            if abs(t2 - t1) < min_time:
                small_merged[-1].extend(segment)
                continue
        small_merged.append(segment)
    merged_segments = small_merged

    # Convert indices back to image paths
    # And split based on hard boundaries (location/time gaps) — this is done after the feature-based segmentation to avoid splitting on transient visual changes within the same location/activity.
    image_segments: list[list[str]] = []
    for segment in merged_segments:
        segment_paths = [image_paths[i] for i in segment]
        mini_segments = []
        for path in segment_paths:
            if path in boundaries and mini_segments:
                image_segments.append(mini_segments)
                mini_segments = []

            mini_segments.append(path)

        if mini_segments:
            image_segments.append(mini_segments)
        else:
            # edge case: if the last image in the segment is a boundary, we need to add the final mini_segment
            image_segments.append(segment_paths)

    logger.info(f"Segmented into {len(image_segments)} segments.")
    return image_segments


def find_first_unsegmented_timestamp(session, device_id, date: Optional[str] = None):
    stmt = (
        select(Image.timestamp)
        .where(
            Image.segment_id.is_(None),
            Image.deleted == False,
            Image.device == device_id,
            Image.date == date,
        )
        .order_by(Image.timestamp.asc())
        .limit(1)
    )
    result = session.execute(stmt).scalars().first()
    return result


def load_all_segments(
    session,
    device_id: str,
    date: str,
    *,
    skip_annotations: bool = False,
    job_id: Optional[str] = None,
):
    # reset_all_segments()
    first_unsegmented_time = find_first_unsegmented_timestamp(session, device_id, date)
    if first_unsegmented_time is None:
        logger.info("All images are already segmented. No reset needed.")
        return

    # Reset all the segments after the first unsegmented timestamp
    logger.info(
        f"First unsegmented image timestamp: {first_unsegmented_time}. Resetting segments for all images from this timestamp onwards..."
    )
    session.execute(
        update(Image)
        .where(
            and_(
                Image.timestamp >= first_unsegmented_time,
                Image.device == device_id,
                Image.date == date,
                Image.deleted == False,
            )
        )
        .values(segment_id=None)
    )
    session.commit()

    job = redis_client.get_json(f"processing_job:{job_id}") if job_id else None

    # Check exisiting segments
    stmt = (
        select(Image.segment_id)
        .where(
            Image.segment_id.isnot(None),
            Image.device == device_id,
            Image.date == date,
        )
        .distinct()
    )
    segment_ids = session.execute(stmt).scalars().all()

    # Remove None
    segment_ids = [sid for sid in segment_ids if sid is not None]
    max_id = 0
    if segment_ids:
        max_id = max(segment_ids) + 1
        logger.debug(f"Existing segments found. Next segment ID: {max_id}")

    new_records = (
        session.execute(
            select(Image)
            .where(
                Image.segment_id.is_(None),
                Image.deleted == False,
                Image.device == device_id,
                Image.date == date,
            )
            .order_by(Image.image_path.desc())
            .limit(50000)
        )
        .scalars()
        .all()
    )

    new_records = [_orm_to_lifelog(rec) for rec in new_records]
    new_records = list(new_records)
    paths = [record.image_path for record in new_records]
    if len(new_records) == 0 or len(paths) == 0:
        logger.info("No new images to segment. Exiting.")
        return

    now = datetime.now(timezone.utc)
    last_image_time = new_records[-1].local_timestamp or new_records[-1].timestamp.astimezone(timezone.utc)

    if len(paths) < 20 and now - last_image_time < timedelta(minutes=15):
        logger.info(
            f"Not enough new images to segment ({len(paths)}), and last image is new ({last_image_time}). Skipping segmentation for now."
        )
        return

    segments = segment_images(session, device_id, paths, reverse=False)
    logger.info(f"Total segments created: {len(segments)}")

    job = redis_client.get_json(f"processing_job:{job_id}") if job_id else None
    tracked_files = job.get("all_files", []) if job else []
    tracked_files_set = set(tracked_files)

    for i, segment in tqdm(
        enumerate(segments),
        desc=f"Processing segments for {device_id} on {date}",
        total=len(segments),
    ):
        segment_id = max_id + i
        session.execute(
            update(Image)
            .where(
                Image.image_path.in_(segment),
                Image.device == device_id,
                Image.date == date,
            )
            .values(segment_id=segment_id)
        )
        session.commit()

        if not skip_annotations:
            try:
                from tasks import describe_segment_task  # noqa: PLC0415
                describe_segment_task.delay(
                    device_id,
                    date,
                    [compress_image(f"{device_id}/{i}") for i in segment],
                    segment_id,
                )
                DaySummaryRecord.update_one(
                    {"date": date, "device": device_id},
                    {"$set": {"updated": True}},
                    upsert=True,
                )
            except Exception:
                pass

        if job is not None and tracked_files_set:
            if (i + 1) % 10 == 0:
                job["progress"] = 0.7 + (i / len(segments)) * 0.3
                job["message"] = (
                    f"Segmented {i}/{len(tracked_files)} images. Currently processing segment {max_id + i}."
                )
                redis_client.set_json(f"processing_job:{job_id}", job)

    session.flush()  # ensure all updates are sent to the database
    if job is not None:
        job["progress"] = 1.0
        job["message"] = "Segmentation complete."
        redis_client.set_json(f"processing_job:{job_id}", job)


def pick_representative_index_for_segment(
    seg_paths: List[str],
    seg_feats: np.ndarray,
    query_embedding: Optional[np.ndarray] = None,
    alpha_centroid: float = 0.5,
) -> List[str]:
    """
    segment_feature_indices: indices of images belonging to the segment
    all_features: np.ndarray of shape (N, D) with CLIP features for the whole day

    Returns:
        index (int) into all_features of the representative image.
    """
    if len(seg_paths) == 0:
        raise ValueError("Segment has no images")

    # L2-normalise (defensive; CLIP features are often already normalised)
    seg_feats = seg_feats / np.linalg.norm(seg_feats, axis=1, keepdims=True)

    # Centroid of the segment
    centroid = seg_feats.mean(axis=0)
    centroid /= np.linalg.norm(centroid) + 1e-8

    # Cosine similarity to centroid == dot product (after normalisation)
    sim_centroid = seg_feats @ centroid  # (N_seg,)
    num_thumbnails = choose_num_thumbnails(len(seg_paths))

    if query_embedding is not None:
        # Normalise query embedding
        q = query_embedding.astype(np.float32)
        q /= np.linalg.norm(q) + 1e-8

        # Similarity to query
        sim_query = seg_feats @ q  # (N_seg,)

        # Combine both: weighted sum
        # alpha_centroid * sim_centroid + (1 - alpha_centroid) * sim_query
        alpha = alpha_centroid
        combined = alpha * sim_centroid + (1.0 - alpha) * sim_query
        best_indices = np.argsort(combined)[-num_thumbnails:]
    else:
        # No query: just use centroid similarity
        best_indices = np.argsort(sim_centroid)[-num_thumbnails:]

    best_images = [seg_paths[i] for i in best_indices]
    return best_images

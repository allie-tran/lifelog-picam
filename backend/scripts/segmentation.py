import math
from datetime import datetime
from typing import List, Optional

import numpy as np
from app_types import AppFeatures
from constants import SEARCH_MODEL, SEGMENT_THRESHOLD
from database.types import DaySummaryRecord, ImageRecord
from database.vector_database import fetch_embeddings
from sessions.redis import RedisClient
from tqdm.auto import tqdm

from scripts.describe_segments import describe_segment
from scripts.utils import compress_image

redis_client = RedisClient()


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


def ema_features(features, alpha=0.4):
    weights = (1 - alpha) ** np.arange(features.shape[0])
    weights = weights[::-1]  # reverse to align powers

    # cumulative weighted sum
    cum = np.cumsum(features[::-1] * weights[:, None], axis=0)
    ema_rev = alpha * cum / weights[:, None]

    return ema_rev[::-1]


def segment_images(
    device_id: str, features, image_paths, deleted_images: set[str], reverse=True
) -> list[list[str]]:
    if len(features) == 0:
        return []

    # Get physical boundaries first (time difference too large)
    boundaries = set()
    time_threshold = 2 * 60 * 1000  # 15 minutes in milliseconds
    min_time = 2 * 60 * 1000  # 5 minutes in milliseconds

    timestamp = ImageRecord.find(
        filter={"image_path": {"$in": image_paths}, "device": device_id}
    )
    path_to_time = {record.image_path: record.timestamp for record in timestamp}
    for img in image_paths:
        if img not in path_to_time:
            print("Error: Missing timestamp for image:", img)
            raise ValueError(f"Missing timestamp for image: {img}")

    for i in range(1, len(image_paths)):
        t1 = path_to_time[image_paths[i - 1]]
        t2 = path_to_time[image_paths[i]]
        if abs(t2 - t1) > time_threshold:
            boundaries.add(image_paths[i])

    # Sort the features and image paths based on the image_pahts
    sorted_indices = np.argsort(image_paths)
    if reverse:
        sorted_indices = sorted_indices[::-1]

    features = features[sorted_indices]
    image_paths = [image_paths[i] for i in sorted_indices]

    # Smooth the features by exponential moving average
    # features = ema_features(features, alpha=0.3)
    # Normalise
    # features = features / np.linalg.norm(features, axis=1, keepdims=True)
    k = SEGMENT_THRESHOLD

    # Calculate all distances
    distances = np.linalg.norm(features[1:] - features[:-1], axis=1)
    print(distances)

    # Dynamic threshold: mean + std
    mean_dist = np.mean(distances)
    std_dist = np.std(distances)
    dynamic_threshold = mean_dist + std_dist * 1.5
    k = dynamic_threshold
    if np.isnan(k) or np.isinf(k):
        k = SEGMENT_THRESHOLD
    print(f"Dynamic threshold for segmentation: {k}")

    # Compare each feature vector with the previous one
    segments: list[list[int]] = []
    current_segment = [0]
    for i in range(1, len(features)):
        image_path = image_paths[i]

        if image_path in deleted_images:
            continue

        start_new_segment = False
        if image_path in boundaries:
            start_new_segment = True
        else:
            distance = distances[i - 1]
            if distance > k:
                start_new_segment = True

        if start_new_segment:
            segments.append(current_segment)
            current_segment = [i]
        else:
            current_segment.append(i)

    if current_segment:
        segments.append(current_segment)

    # Merge segments that are too similar
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

    # Merge small segments
    merged_segments = []
    for segment in segments:
        if len(segment) < 3 and merged_segments:
            # check the time
            start_image = image_paths[segment[0]]
            end_image = image_paths[merged_segments[-1][-1]]
            t1 = path_to_time[start_image]
            t2 = path_to_time[end_image]
            if abs(t2 - t1) < min_time:
                merged_segments[-1].extend(segment)
                continue
        merged_segments.append(segment)

    # Convert indices back to image paths
    image_segments: list[list[str]] = []
    for segment in merged_segments:
        segment_paths = [image_paths[i] for i in segment]
        image_segments.append(segment_paths)

    print(f"Segmented into {len(image_segments)} segments.")
    return image_segments


def reset_all_segments(device_id):
    print("Resetting all segments...")
    ImageRecord.update_many(
        filter={"device": device_id},
        data={"$unset": {"segment_id": None}},
    )


def find_first_unsegmented_timestamp(device_id, date: Optional[str] = None):
    record = ImageRecord.find(
        filter={
            "segment_id": None,
            "deleted": False,
            "device": device_id,
            **({"date": date} if date else {}),
        },
        sort=[("timestamp", 1)],
        limit=1,
    )
    record = list(record)
    if record:
        return record[0].timestamp
    return None


def load_all_segments(
    device_id: str,
    date: str,
    features: AppFeatures,
    deleted_images: set[str],
    *,
    job_id: Optional[str] = None,
):
    # reset_all_segments()
    first_unsegmented_time = find_first_unsegmented_timestamp(device_id, date)
    if first_unsegmented_time is None:
        print("All images are already segmented. Exiting.")
        return

    # Reset all the segments after the first unsegmented timestamp
    print(
        f"First unsegmented image timestamp: {datetime.fromtimestamp(int(first_unsegmented_time / 1000))}"
    )
    ImageRecord.update_many(
        filter={
            "timestamp": {"$gte": first_unsegmented_time},
            "device": device_id,
            "date": date,
            "deleted": {"$ne": True},
        },
        data={"$unset": {"segment_id": None}},
    )

    job = redis_client.get_json(f"processing_job:{job_id}") if job_id else None

    # Check exisiting segments
    segment_ids = ImageRecord.find(
        filter={
            "segment_id": {"$exists": True},
            "device": device_id,
            "date": date,
        },
        distinct="segment_id",
    )
    # Remove None
    segment_ids = [sid for sid in segment_ids if sid is not None]
    max_id = 0
    if segment_ids:
        max_id = max(segment_ids) + 1
        print(f"Existing segments found. Next segment ID: {max_id}")

    new_records = ImageRecord.find(
        filter={
            "$or": [
                {"segment_id": {"$exists": False}},
                {"segment_id": None},
            ],
            "deleted": {"$ne": True},
            "device": device_id,
            "date": date,
        },
        sort=[("image_path", -1)],
        limit=50000,
    )

    new_records = list(new_records)
    print(f"Found {len(new_records)} new images to segment.")
    paths = [record.image_path for record in new_records]

    now = datetime.now().timestamp() * 1000
    last_image_time = new_records[-1].timestamp
    if len(paths) < 100 and now - last_image_time < 60 * 60 * 1000:
        print(
            f"Not enough new images to segment ({len(paths)}), and last image is new ({datetime.fromtimestamp(int(last_image_time / 1000))}). Skipping segmentation for now."
        )
        return

    collection = features[device_id][SEARCH_MODEL].collection
    paths, feats = fetch_embeddings(collection, paths, device_id)

    print(f"Segmenting {len(feats)} images...")
    print(f"Features shape for segmentation: {feats.shape}")
    segments = segment_images(device_id, feats, paths, deleted_images, reverse=False)
    print(f"Total segments created: {len(segments)}")

    job = redis_client.get_json(f"processing_job:{job_id}") if job_id else None
    tracked_files = job.get("all_files", []) if job else []
    tracked_files_set = set(tracked_files)

    for i, segment in tqdm(
        enumerate(segments), desc="Updating segments", total=len(segments)
    ):
        segment_id = max_id + i
        print(segment_id, date, segment[:3], "...", segment[-3:])
        ImageRecord.update_many(
            filter={
                "image_path": {"$in": segment},
                "device": device_id,
                "date": date,
            },
            data={"$set": {"segment_id": max_id + i}},
        )

        if device_id == "allie":
            try:
                describe_segment(
                    device_id,
                    date,
                    [compress_image(f"{device_id}/{i}") for i in segment],
                    segment_idx=segment_id,
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

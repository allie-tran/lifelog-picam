import os

import numpy as np
from PIL import Image

from database.types import ImageRecord
from constants import DIR
from scripts.querybank_norm import BETA, apply_qb_norm_to_query
from visual import siglip_model

os.makedirs(f"{DIR}/thumbnails", exist_ok=True)


def compress_image(image_path, quality=85):
    rel_path = image_path.replace(DIR + "/", "")
    output_path = f"{DIR}/thumbnails/{rel_path.rsplit('.', 1)[0]}.webp"
    if os.path.exists(output_path):
        return output_path

    img = Image.open(image_path)
    os.makedirs(os.path.dirname(output_path), exist_ok=True)
    # Resize to max 800x800 while maintaining aspect ratio
    img.thumbnail((800, 800))
    img.save(output_path, "WEBP", quality=quality)
    return output_path


def make_video_thumbnail(video_path, quality=85):
    rel_path = video_path.replace(DIR + "/", "")
    output_path = f"{DIR}/thumbnails/{rel_path.rsplit('.', 1)[0]}.webp"
    if os.path.exists(output_path):
        return output_path

    os.makedirs(os.path.dirname(output_path), exist_ok=True)
    status = os.system(
        f"ffmpeg -y -i '{video_path}' -ss 00:00:01.000 -vframes 1 -vf 'scale=800:-1' '{output_path}'"
    )
    if status != 0:
        print("Failed to generate thumbnail for video:", video_path)
        os.remove(output_path) if os.path.exists(output_path) else None
        return None
    return output_path


feature_path = "siglip_features.npz"
DIM = 1152


def load_features():
    try:
        data = np.load(feature_path, allow_pickle=True)
        features = data["features"]
        image_paths = data["image_paths"].tolist()
        min_value = min(len(image_paths), features.shape[0])
        features = features[:min_value]
        image_paths = image_paths[:min_value]
        assert (
            features.shape[1] == DIM
        ), f"Feature dimension mismatch: {features.shape[1]} != {DIM}"
        assert len(features) == len(
            image_paths
        ), f"{len(features)} != {len(image_paths)}"

        # Sort by image paths
        sorted_indices = np.argsort(image_paths)
        features = features[sorted_indices]
        image_paths = [image_paths[i] for i in sorted_indices]

        print(f"Loaded {len(image_paths)} features.")
    except FileNotFoundError:
        features, image_paths = np.empty((0, DIM), dtype=np.float32), []
    return features, image_paths


def save_features(features, image_paths):
    np.savez_compressed(feature_path, features=features, image_paths=image_paths)


def encode_image(image_path: str, features, image_paths):
    image_paths = image_paths[:len(features)]
    path = f"{DIR}/{image_path}"
    if image_path.endswith(".mp4") or image_path.endswith(".h264"):
        # use video thumbnail
        new_path = make_video_thumbnail(f"{DIR}/{image_path}")
        if new_path:
            path = new_path

    vector = siglip_model.encode_image(path)
    image_paths.append(image_path)
    if len(vector.shape) == 0:
        vector = vector.reshape(1, -1)
    features = np.vstack([features, vector])
    # assert len(features) == len(image_paths), f"{len(features)} != {len(image_paths)}"
    return vector, features, image_paths


def retrieve_image(
    text: str,
    features,
    image_paths,
    deleted_images: set[str],
    k=100,
    retrieved_videos=None,
    normalizing_sum=None,
    remove=np.array([]),
):
    if len(features) == 0:
        print("No features available.")
        return []

    features = features / np.linalg.norm(features, axis=1, keepdims=True)
    query_vector = siglip_model.encode_text(text, normalize=True)

    # Apply query bank normalization
    if retrieved_videos is not None and normalizing_sum is not None:
        similarities = apply_qb_norm_to_query(
            query_vector,
            features,
            retrieved_videos,
            normalizing_sum,
            BETA,
        )
    else:
        similarities = features @ query_vector

    # Exclude deleted images
    for i, path in enumerate(image_paths):
        if path in deleted_images:
            similarities[i] = -1.0  # Set similarity to -1 to exclude

    # Exclude specific indices
    similarities[remove] = -1.0

    top_indices = np.argsort(similarities)[-k:][::-1]

    results = []
    for idx in top_indices:
        results.append(ImageRecord(
            image_path=image_paths[idx],
            date=image_paths[idx].split("/")[0],
            thumbnail=image_paths[idx]
            .replace(".jpg", ".webp")
            .replace(".png", ".webp"),
            timestamp=os.path.getmtime(f"{DIR}/{image_paths[idx]}") * 1000,
            is_video=image_paths[idx].endswith(".mp4")
            or image_paths[idx].endswith(".h264"),
        ))
    return results


def get_similar_images(
    image: str,
    features,
    image_paths,
    deleted_images: set[str],
    k=100,
    retrieved_videos=None,
    normalizing_sum=None,
    remove=np.array([]),
):
    if len(features) == 0:
        print("No features available.")
        return []

    features = features / np.linalg.norm(features, axis=1, keepdims=True)
    if image in image_paths:
        query_vector = features[image_paths.index(image)]
    else:
        query_vector, _, _ = encode_image(image, np.empty((0, DIM)), [])
        query_vector = query_vector / np.linalg.norm(query_vector)

    # Apply query bank normalization
    if retrieved_videos is not None and normalizing_sum is not None:
        similarities = apply_qb_norm_to_query(
            query_vector,
            features,
            retrieved_videos,
            normalizing_sum,
            BETA,
        )
    else:
        similarities = features @ query_vector

    # Exclude deleted images
    for i, path in enumerate(image_paths):
        if path in deleted_images:
            similarities[i] = -1.0  # Set similarity to -1 to exclude

    # Exclude specific indices
    similarities[remove] = -1.0

    top_indices = np.argsort(similarities)[-k:][::-1]

    results = []
    for idx in top_indices:
        results.append(
            ImageRecord(
                image_path=image_paths[idx],
                date=image_paths[idx].split("/")[0],
                thumbnail=image_paths[idx]
                .replace(".jpg", ".webp")
                .replace(".png", ".webp"),
                timestamp=os.path.getmtime(f"{DIR}/{image_paths[idx]}") * 1000,
                is_video=image_paths[idx].endswith(".mp4")
                or image_paths[idx].endswith(".h264"),
            )
        )
    return results

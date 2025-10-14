import os

import numpy as np
from PIL import Image

from constants import DIR
from visual import siglip_model

os.makedirs(f"{DIR}/thumbnails", exist_ok=True)


def compress_image(image_path, quality=85):
    rel_path = image_path.replace(DIR + "/", "")
    output_path = f"{DIR}/thumbnails/{rel_path.rsplit('.', 1)[0]}.webp"
    if os.path.exists(output_path):
        return

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
        return

    os.makedirs(os.path.dirname(output_path), exist_ok=True)
    os.system(f"ffmpeg -y -i '{video_path}' -ss 00:00:01.000 -vframes 1 -vf 'scale=800:-1' '{output_path}'")
    img = Image.open(output_path)
    img.save(output_path, "WEBP", quality=quality)
    return output_path

feature_path = "siglip_features.npz"
DIM = 1152

def load_features():
    try:
        data = np.load(feature_path, allow_pickle=True)
        features = data["features"]
        image_paths = data["image_paths"].tolist()
        assert features.shape[1] == DIM, f"Feature dimension mismatch: {features.shape[1]} != {DIM}"
        assert len(features) == len(image_paths), f"{len(features)} != {len(image_paths)}"

        # remove .mp4 and .h264 and .webp files from features and image_paths
        filtered_features = []
        filtered_image_paths = []
        for feat, path in zip(features, image_paths):
            if not os.path.exists(f"{DIR}/{path}"):
                continue
            if not (path.endswith(".mp4") or path.endswith(".h264") or path.endswith(".webp")):
                filtered_features.append(feat)
                filtered_image_paths.append(path)

        features = np.array(filtered_features)
        image_paths = filtered_image_paths
        print(f"Loaded {len(image_paths)} features.")
    except FileNotFoundError:
        features, image_paths = np.empty((0, DIM), dtype=np.float32), []
    return features, image_paths



def save_features(features, image_paths):
    np.savez_compressed(feature_path, features=features, image_paths=image_paths)


def encode_image(image_path: str, features, image_paths):
    if image_path.endswith(".mp4") or image_path.endswith(".h264"):
        # use video thumbnail
        # path = f"{DIR}/thumbnails/{image_path.rsplit('.', 1)[0]}.webp"
        # print("Using video thumbnail:", path)
        vector = np.ones((DIM,), dtype=np.float32)
    else:
        path = f"{DIR}/{image_path}"
        vector = siglip_model.encode_image(path)

    image_paths.append(image_path)
    if len(vector.shape) == 0:
        vector = vector.reshape(1, -1)
    features = np.vstack([features, vector])
    assert len(features) == len(image_paths), f"{len(features)} != {len(image_paths)}"
    return vector, features, image_paths


def retrieve_image(text: str, features, image_paths, deleted_images: set[str], k=100):
    if len(features) == 0:
        print("No features available.")
        return []

    features = features / np.linalg.norm(features, axis=1, keepdims=True)
    query_vector = siglip_model.encode_text(text, normalize=True)

    similarities = features @ query_vector

    # Exclude deleted images
    for i, path in enumerate(image_paths):
        if path in deleted_images:
            similarities[i] = -1.0  # Set similarity to -1 to exclude

    top_indices = np.argsort(similarities)[-k:][::-1]

    results = []
    for idx in top_indices:
        results.append(
            {
                "image_path": image_paths[idx].split(".")[0],
                "timestamp": os.path.getmtime(f"{DIR}/{image_paths[idx]}") * 1000,
                "similarity": float(similarities[idx]),
            }
        )
    return results

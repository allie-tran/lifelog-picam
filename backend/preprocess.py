import glob
import os
from typing import List

import numpy as np
from PIL import Image, ImageDraw, ImageFilter

from app_types import (
    AppFeatures,
    CLIPFeatures,
    CustomFastAPI,
    DeviceFeatures,
    ObjectDetection,
)
from constants import DIR, THUMBNAIL_DIR
from database.types import ImageRecord
from database.vector_database import create_collection, insert_batch_embeddings
from visual import clip_model

os.makedirs(THUMBNAIL_DIR, exist_ok=True)


def get_thumbnail_path(image_path: str) -> tuple[str, bool]:
    rel_path = image_path.replace(DIR + "/", "")
    output_path = f"{THUMBNAIL_DIR}/{rel_path.rsplit('.', 1)[0]}.webp"
    if os.path.exists(output_path):
        return output_path, True
    return output_path, False


def compress_image(image_path, quality=85):
    output_path, exists = get_thumbnail_path(image_path)
    if exists:
        return output_path

    img = Image.open(image_path)
    os.makedirs(os.path.dirname(output_path), exist_ok=True)
    # Resize to max 800x800 while maintaining aspect ratio
    img.thumbnail((800, 800))
    img.save(output_path, "WEBP", quality=quality)
    return output_path


def get_blurred_image(image_path: str, boxes: List[ObjectDetection], blur_strength=30):
    image = Image.open(image_path)
    for box in boxes:
        x1, y1, x2, y2 = box.bbox

        # expand box by 10%
        box_width = x2 - x1
        box_height = y2 - y1
        x1 = max(0, int(x1 - box_width * 0.1))
        y1 = max(0, int(y1 - box_height * 0.1))
        x2 = min(image.width, int(x2 + box_width * 0.1))
        y2 = min(image.height, int(y2 + box_height * 0.1))

        try:
            # adjusting the strength of the blur based on box size
            box_area = (x2 - x1) * (y2 - y1)
            adjusted_blur_strength = (
                int(blur_strength * (box_area / (image.width * image.height))) * 100
            )
            adjusted_blur_strength = max(30, min(adjusted_blur_strength, 1000))
            region = image.crop((x1, y1, x2, y2))
            blurred_region = region.filter(
                ImageFilter.GaussianBlur(radius=adjusted_blur_strength)
            )

            # Paste in an oval
            mask = Image.new("L", (x2 - x1, y2 - y1), 0)
            draw = ImageDraw.Draw(mask)
            draw.ellipse(
                [(0, 0), (x2 - x1, y2 - y1)],
                fill=255,
            )
            image.paste(blurred_region, (x1, y1), mask)
        except Exception as e:
            print(f"Error blurring region ({x1}, {y1}, {x2}, {y2}): {e}")
            continue
    return image


def blur_image(image_path: str, boxes: List[ObjectDetection], blur_strength=30):
    image = get_blurred_image(image_path, boxes, blur_strength)
    # save in webp format
    image.thumbnail((800, 800))
    rel_path = image_path.replace(DIR + "/", "")
    output_path = f"{THUMBNAIL_DIR}/{rel_path.rsplit('.', 1)[0]}.webp"
    os.makedirs(os.path.dirname(output_path), exist_ok=True)
    image.save(output_path, "WEBP")


def make_video_thumbnail(video_path):
    rel_path = video_path.replace(DIR + "/", "")
    output_path = f"{THUMBNAIL_DIR}/{rel_path.rsplit('.', 1)[0]}.webp"
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


feature_dir = "features"
feature_path = "siglip_features.npz"
DIM = 1152


def load_features(app: CustomFastAPI) -> AppFeatures:
    app_features = AppFeatures()
    try:
        for device in os.listdir(feature_dir):
            device_features = DeviceFeatures()
            for model in app.models:
                features = None
                image_paths = []
                matches = glob.glob(f"{feature_dir}/{device}/{model}*.features.npz")
                for match in sorted(matches):
                    data = np.load(match, allow_pickle=True)
                    feats = data["features"]
                    paths = data["image_paths"].tolist()
                    if features is None:
                        features = feats
                    else:
                        features = np.vstack([features, feats])
                    image_paths.extend(paths)
                print(
                    f"Loaded {len(image_paths)} features for device {device}, model {model}"
                )
                device_features[model] = CLIPFeatures(
                    features=features,
                    image_paths=image_paths,
                    image_paths_to_index={
                        path: idx for idx, path in enumerate(image_paths)
                    },
                )
            app_features[device] = device_features
    except FileNotFoundError:
        print("No existing features found.")

    # save to zvec
    batch_size = 50000
    for device in app_features:
        for model in app_features[device]:
            print(
                f"Indexing features for device {device}, model {model} into vector database."
            )
            feats = app_features[device][model].features
            paths = app_features[device][model].image_paths

            collection = create_collection(device, model)
            size = len(paths)
            for i in tqdm(
                range(0, size, batch_size),
                desc=f"Indexing features for {device} {model}",
            ):
                batch_feats = feats[i : i + batch_size]
                batch_paths = paths[i : i + batch_size]
                insert_batch_embeddings(collection, batch_feats, batch_paths)

    return app_features


def save_features(features: AppFeatures):
    return
    for device in features.keys():
        for model in features[device].keys():
            feats = features[device][model]
            print(
                f"Saving {len(feats.image_paths)}, {feats.features.shape} features for device {device}, model {model}"
            )
            min_value = min(len(feats.image_paths), feats.features.shape[0])
            feats.features = feats.features[:min_value]
            feats.image_paths = feats.image_paths[:min_value]
            sorted_indices = np.argsort(feats.image_paths)
            feats.features = feats.features[sorted_indices]
            feats.image_paths = [feats.image_paths[i] for i in sorted_indices]
            print("Sorted features and image paths.")
            chunk_size = 50000
            for i in range(0, len(feats.image_paths), chunk_size):
                batch_features = feats.features[i : i + chunk_size]
                batch_image_paths = feats.image_paths[i : i + chunk_size]
                np.savez_compressed(
                    f"{feature_dir}/{device}/{model}_{i//chunk_size}.features.npz",
                    features=batch_features,
                    image_paths=batch_image_paths,
                )
            # np.savez_compressed(
            #     f"{feature_dir}/{device}/{model}.features.npz",
            #     features=feats.features,
            #     image_paths=feats.image_paths,
            # )
            print(f"Saved features for device {device}, model {model} to disk.")
    return features


def encode_image(
    device_id: str,
    image_path: str,
    features: CLIPFeatures,
):
    features.image_paths = features.image_paths[: len(features.features)]
    try:
        path = f"{DIR}/{device_id}/{image_path}"
        if image_path.endswith(".mp4") or image_path.endswith(".h264"):
            # use video thumbnail
            new_path = make_video_thumbnail(f"{DIR}/{device_id}/{image_path}")
            if new_path:
                path = new_path

        vector = clip_model.encode_image(path)
        features.image_paths.append(image_path)
        if len(vector.shape) == 0:
            vector = vector.reshape(1, -1)
        if features.features.shape[0] == 0:
            features.features = vector
        else:
            features.features = np.vstack([features.features, vector])
        features.image_paths_to_index[image_path] = len(features.image_paths) - 1
        # assert len(features) == len(image_paths), f"{len(features)} != {len(image_paths)}"
        return vector, features
    except Exception as e:
        print(e)
        print(f"Error encoding image {image_path}")
        if os.path.exists(f"{DIR}/{device_id}/{image_path}"):
            os.remove(f"{DIR}/{device_id}/{image_path}")
        return None, features


def retrieve_image(
    device_id: str,
    text: str,
    sort_by,
    feats,
    paths,
    deleted_images: set[str],
    k=100,
    retrieved_videos=None,
    normalizing_sum=None,
    remove=np.array([]),
):
    if len(feats) == 0:
        print("No features available.")
        return {}

    feats = feats / np.linalg.norm(feats, axis=1, keepdims=True)
    query_vector = clip_model.encode_text(text, normalize=True)

    # # Apply query bank normalization
    # if retrieved_videos is not None and normalizing_sum is not None:
    #     try:
    #         similarities = apply_qb_norm_to_query( query_vector,
    #             feats,
    #             retrieved_videos,
    #             normalizing_sum,
    #             BETA,
    #         )
    #     except Exception as e:
    #         print(f"Error applying QB-Norm: {e}")
    #         similarities = feats @ query_vector
    # else:
    # similarities = feats @ query_vector

    similarities = feats @ query_vector

    # Exclude deleted images
    for i, path in enumerate(paths):
        if path in deleted_images:
            similarities[i] = -1.0  # Set similarity to -1 to exclude

    # Exclude specific indices
    if len(remove) > 0:
        print("Excluding indices:", remove)
        similarities[remove] = -1.0

    top_indices = np.argsort(similarities)[-k:][::-1]
    top_images = np.array(paths)[top_indices]

    sort_by_timestamp = sort_by == "time"
    if sort_by_timestamp:
        image_records = ImageRecord.find(
            filter={
                "device": device_id,
                "image_path": {"$in": top_images.tolist()},
            },
            sort=[("timestamp", -1)],
        )
        # group by segment id
        segments: dict[str, List[ImageRecord]] = {}
        for image_record in image_records:
            if image_record.segment_id in segments:
                segments[image_record.segment_id].append(image_record)
            else:
                segments[image_record.segment_id] = [image_record]
        return list(segments.values())
    else:
        # sort by relevance
        image_records = ImageRecord.find(
            filter={
                "device": device_id,
                "image_path": {"$in": top_images.tolist()},
            }
        )
        print(top_images)
        image_to_image_record = {img.image_path: img for img in image_records}
        segments: dict[str, List[ImageRecord]] = {}
        for image in top_images:
            image_record = image_to_image_record.get(image)
            if image_record:
                segment_id = image_record.segment_id
                if segment_id in segments:
                    segments[segment_id].append(image_record)
                else:
                    segments[segment_id] = [image_record]

        return list(segments.values())


def get_similar_images(
    device_id: str,
    image: str,
    feats,
    paths,
    deleted_images: set[str],
    k=100,
    retrieved_videos=None,
    normalizing_sum=None,
    remove=np.array([]),
):
    if len(feats) == 0:
        print("No features available.")
        return []

    feats = feats / np.linalg.norm(feats, axis=1, keepdims=True)
    if image in paths:
        query_vector = feats[paths.index(image)]
    else:
        # query_vector, *_ = encode_image(device_id, image, np.empty((0, DIM)), [])
        try:
            path = image
            if path.endswith(".mp4") or path.endswith(".h264"):
                # use video thumbnail
                new_path = make_video_thumbnail(f"{DIR}/{device_id}/{image}")
                if new_path:
                    path = new_path

            query_vector = clip_model.encode_image(path)
            query_vector = query_vector / np.linalg.norm(query_vector)
            query_vector = query_vector.reshape(-1, 1)
        except Exception as e:
            print(f"Error encoding image {image}: {e}")
            return []

    similarities = feats @ query_vector

    # Exclude deleted images
    for i, path in enumerate(paths):
        if path in deleted_images:
            similarities[i] = -1.0  # Set similarity to -1 to exclude

    # Exclude specific indices
    similarities[remove] = -1.0

    top_indices = np.argsort(similarities)[-k:][::-1]
    top_images = np.array(paths)[top_indices]
    print("Similar images:", top_images)
    return ImageRecord.find(
        filter={
            "device": device_id,
            "image_path": {"$in": top_images.tolist()},
        },
        sort=[("timestamp", -1)],
    )

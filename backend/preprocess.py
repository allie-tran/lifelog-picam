import glob
import os
from typing import List

import numpy as np
from PIL import Image, ImageDraw, ImageFilter
from tqdm import tqdm

from app_types import (
    AppFeatures,
    CLIPFeatures,
    CustomFastAPI,
    DeviceFeatures,
    ObjectDetection,
)
from constants import DIR, THUMBNAIL_DIR
from database.types import ImageRecord
from database.vector_database import (
    create_collection,
    insert_batch_embeddings,
    insert_embedding,
    open_collection,
    search_similar_embeddings,
    search_similar_embeddings_by_id,
)
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
    for device in os.listdir(feature_dir):
        device_features = DeviceFeatures()
        app_features[device] = device_features
        collection = open_collection(device, "conclip")
        app_features[device]["conclip"] = CLIPFeatures(collection=collection)

    app.features = app_features
    return app_features

def encode_image(
    device_id: str,
    image_path: str,
    features: CLIPFeatures,
):
    try:
        path = f"{DIR}/{device_id}/{image_path}"
        if image_path.endswith(".mp4") or image_path.endswith(".h264"):
            # use video thumbnail
            new_path = make_video_thumbnail(f"{DIR}/{device_id}/{image_path}")
            if new_path:
                path = new_path

        vector = clip_model.encode_image(path)
        if len(vector.shape) == 0:
            vector = vector.reshape(1, -1)

        insert_embedding(features.collection, vector.flatten(), image_path)
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
    features: CLIPFeatures,
    sort_by,
    deleted_images: set[str],
    k=100,
    retrieved_videos=None,
    normalizing_sum=None,
    remove=np.array([]),
):
    query_vector = clip_model.encode_text(text, normalize=True)
    docs = search_similar_embeddings(
        features.collection,
        query_vector.flatten(),
        top_k=k,
    )
    image_paths = [doc.fields["image_path"] for doc in docs]
    top_images = [path for path in image_paths if path not in deleted_images and path not in remove]

    sort_by_timestamp = sort_by == "time"
    if sort_by_timestamp:
        image_records = ImageRecord.find(
            filter={
                "device": device_id,
                "image_path": {"$in": top_images},
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
                "image_path": {"$in": top_images},
            }
        )
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
    features: CLIPFeatures,
    deleted_images: set[str],
    k=100,
    retrieved_videos=None,
    normalizing_sum=None,
    remove=np.array([]),
):
    if "temp" in image:
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
        except Exception as e:
            print(f"Error encoding image {image}: {e}")
            return []

        docs = search_similar_embeddings(
            features.collection,
            query_vector,
            top_k=k,
        )
    else:
        docs = search_similar_embeddings_by_id(
            features.collection,
            image,
            top_k=k,
        )

    top_images = [doc.fields["image_path"] for doc in docs]
    top_images = [path for path in top_images if path not in deleted_images and path not in remove]
    print("Similar images:", top_images)
    return ImageRecord.find(
        filter={
            "device": device_id,
            "image_path": {"$in": top_images},
        },
        sort=[("timestamp", -1)],
    )

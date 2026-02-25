import os
from typing import List

import numpy as np

from app_types import AppFeatures, CLIPFeatures, CustomFastAPI, DeviceFeatures
from auth.ortho import apply_transformation, get_matrix
from constants import DIR, THUMBNAIL_DIR
from database.types import ImageRecord
from database.vector_database import (
    open_collection,
    search_similar_embeddings,
    search_similar_embeddings_by_id,
)
from scripts.face_recognition import open_face_collection
from scripts.utils import make_video_thumbnail
from visual import clip_model

os.makedirs(THUMBNAIL_DIR, exist_ok=True)


def load_features(app: CustomFastAPI) -> AppFeatures:
    feature_dir = "features"
    app_features = AppFeatures()
    for device in os.listdir(feature_dir):
        device_features = DeviceFeatures()
        app_features[device] = device_features
        collection = open_collection(device, "conclip")
        app_features[device]["conclip"] = CLIPFeatures(collection=collection)
        app_features[device]["faces"] = CLIPFeatures(
            collection=open_face_collection(device)
        )

    app.features = app_features
    return app_features


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
    query_vector = apply_transformation(query_vector, get_matrix(device_id))

    docs = search_similar_embeddings(
        features.collection,
        query_vector.flatten(),
        top_k=k,
    )
    image_paths = [doc.fields["image_path"] for doc in docs]
    top_images = [
        path
        for path in image_paths
        if path not in deleted_images and path not in remove
    ]

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
            query_vector = query_vector.flatten()
            query_vector = apply_transformation(query_vector, get_matrix(device_id))
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
    top_images = [
        path for path in top_images if path not in deleted_images and path not in remove
    ]
    return ImageRecord.find(
        filter={
            "device": device_id,
            "image_path": {"$in": top_images},
        },
        sort=[("timestamp", -1)],
    )

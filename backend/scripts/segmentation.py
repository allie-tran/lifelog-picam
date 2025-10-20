import numpy as np
from database.types import ImageRecord
from tqdm.auto import tqdm


def segment_images(features, image_paths, deleted_images: set[str], reverse=True):
    if len(features) == 0:
        return []

    # Sort the features and image paths based on the image_pahts
    sorted_indices = np.argsort(image_paths)
    if reverse:
        sorted_indices = sorted_indices[::-1]
    features = features[sorted_indices]

    # Compare each feature vector with the previous one
    segments = []
    current_segment = [image_paths[sorted_indices[0]]]
    k = 0.6  # Threshold for segmentation, can be adjusted
    for i in range(1, len(features)):
        if image_paths[sorted_indices[i]] in deleted_images:
            continue
        distance = np.linalg.norm(features[i] - features[i - 1])
        if distance < k:
            current_segment.append(image_paths[sorted_indices[i]])
        else:
            segments.append(current_segment)
            current_segment = [image_paths[sorted_indices[i]]]
    if current_segment:
        segments.append(current_segment)
    return segments


def reset_all_segments():
    print("Resetting all segments...")
    ImageRecord.update_many(
        filter={"segment_id": {"$exists": True}},
        data={"$unset": {"segment_id": ""}},
    )


def load_all_segments(features, image_paths, deleted_images: set[str]):
    # reset_all_segments()
    print("Loading all segments...")
    # Check exisiting segments
    segment_ids = ImageRecord.find(
        filter={"segment_id": {"$exists": True}},
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
            ]
        },
        sort=[("image_path", -1)],
    )

    image_to_index = {image_path: idx for idx, image_path in enumerate(image_paths)}
    image_paths = [
        record.image_path
        for record in new_records
        if record.image_path in image_to_index
    ]

    if len(image_paths) < 100:
        print("Not enough new images to segment. Exiting.")
        return

    features = np.array(
        [features[image_to_index[image_path]] for image_path in image_paths]
    )

    print(f"Segmenting {len(image_paths)} images...")
    print(f"Features shape for segmentation: {features.shape}")
    segments = segment_images(features, image_paths, deleted_images, reverse=False)
    print(f"Total segments created: {len(segments)}")

    for i, segment in tqdm(enumerate(segments), desc="Updating segments", total=len(segments)):
        ImageRecord.update_many(
            filter={"image_path": {"$in": segment}},
            data={"$set": {"segment_id": max_id + i}},
        )

import os
import numpy as np

def segment_images(features, image_paths, deleted_images: set[str]):
    if len(features) == 0:
        return []
    # Sort the features and image paths based on the image_pahts
    sorted_indices = np.argsort(image_paths)[::-1]
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

def load_all_segments(features, image_paths, deleted_images: set[str]):
    segments = segment_images(features, image_paths, deleted_images)

    image_to_segment = {}
    for segment in segments:
        for image in segment:
            image_to_segment[image] = segment
    return image_to_segment, segments



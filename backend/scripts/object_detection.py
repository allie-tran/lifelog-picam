# You can install it using pip:
# pip install ultralytics

import json
import os
import glob
from typing import Any
from tqdm import tqdm

from facenet_pytorch import MTCNN, InceptionResnetV1
import torch
from typing import List


import cv2
from app_types import ObjectDetection
from ultralytics import YOLO
# from deepface import DeepFace

detect_model = YOLO('yolo11x.pt', task='detect', verbose=False)
classify_model = YOLO('yolo11x-cls.pt', task='classify', verbose=False)
print("Model loaded successfully.")

def extract_object_from_image(
    image_path
):
    frame = cv2.imread(image_path)
    if frame is None:
        return [], []
    results = detect_model(
        frame, verbose=False
    )  # Adjust confidence and iou as needed

    objects = []
    people = []
    for r in results:
        boxes = r.boxes

        for box in boxes:
            x1, y1, x2, y2 = map(
                int, box.xyxy[0]
            )

            conf = box.conf[0]  # Confidence score
            cls = int(box.cls[0])
            class_name = detect_model.names[cls]  # Get class name from model
            h, w, _ = frame.shape
            x1 = max(0, x1)
            y1 = max(0, y1)
            x2 = min(w, x2)
            y2 = min(h, y2)

            if x2 > x1 and y2 > y1:
                objects.append(
                    ObjectDetection(
                        label=class_name,
                        confidence=float(conf),
                        bbox=[x1, y1, x2, y2],
                    )
                )
                if class_name == "person":
                    face_data = get_face_data_from_person_crop(
                        frame[y1:y2, x1:x2]
                    )
                    # Add face bounding boxes to people list
                    for face in face_data:
                        face_bbox = face.bbox
                        # Adjust face bbox coordinates to original image
                        adjusted_bbox = [
                            face_bbox[0] + x1,
                            face_bbox[1] + y1,
                            face_bbox[2] + x1,
                            face_bbox[3] + y1,
                        ]
                        people.append(ObjectDetection(
                            label="face",
                            confidence=face.confidence,
                            bbox=adjusted_bbox,
                            embedding=face.embedding,
                        ))
    return objects, people

PERSON_CONF_THRESHOLD = 0.5

# Initialize once globally
device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
mtcnn = MTCNN(keep_all=True, device=device)
resnet = InceptionResnetV1(pretrained='vggface2').eval().to(device)

def get_face_data_from_person_crop(person_crop) -> List[dict]:
    """
    Detects faces in person_crop, extracts aligned faces and embeddings.
    Returns a list of ObjectDetection-like dictionaries:
    [{'embedding': [], 'bbox': (x1,y1,x2,y2), 'confidence': float}]
    """
    face_data = []

    try:
        # Detect faces and get bounding boxes
        boxes, probs = mtcnn.detect(person_crop)
        if boxes is None:
            return []

        for box, prob in zip(boxes, probs):
            if prob < PERSON_CONF_THRESHOLD:
                continue

            x1, y1, x2, y2 = map(int, box)
            w, h = x2 - x1, y2 - y1

            # Skip boxes almost the same size as the person crop
            size_diff = abs(w - person_crop.shape[1]) + abs(h - person_crop.shape[0])
            if size_diff < 10:
                continue

            # Crop and align the face
            face_crop = person_crop[y1:y2, x1:x2]
            # MTCNN automatically aligns during detection if needed; else you can preprocess here
            face_tensor = mtcnn.extract(person_crop, [(x1, y1, x2, y2)], save_path=None)
            if face_tensor is None or len(face_tensor) == 0:
                continue

            # Compute embedding
            with torch.no_grad():
                embedding = resnet(face_tensor[0].to(device).unsqueeze(0)).squeeze(0).cpu().numpy()

            face_data.append(
                ObjectDetection(
                    label="face",
                    confidence=float(prob),
                    bbox=[x1, y1, x2, y2],
                    embedding=embedding.tolist(),
                )
            )

    except Exception as e:
        print(f"Face processing error: {e}")

    return face_data

# def get_face_data_from_person_crop(person_crop):
#     """
#     Detects faces in the person_crop, extracts aligned faces and their embeddings.
#     Returns a list of dictionaries: [{'embedding': [], 'bbox': (x1,y1,x2,y2)}]
#     """
#     face_data = []
#     try:
#         faces = DeepFace.represent(
#             img_path=person_crop,
#             model_name="Facenet512",
#             enforce_detection=False,
#             detector_backend="yolov8",
#             normalization="Facenet2018",
#         )

#         for face_info in faces:
#             confidence = face_info["face_confidence"]
#             if confidence < PERSON_CONF_THRESHOLD:
#                 continue

#             face = face_info["facial_area"]
#             x, y, w, h = (
#                 face["x"],
#                 face["y"],
#                 face["w"],
#                 face["h"],
#             )
#             # Remove box that are the same size (or similar) as the person crop
#             size_diff = abs(w - person_crop.shape[1]) + abs(h - person_crop.shape[0])
#             if size_diff < 10:  # Adjust threshold as needed
#                 print(
#                     f"Skipping face with size {w}x{h} in person crop of size {person_crop.shape[1]}x{person_crop.shape[0]}"
#                 )
#                 continue

#             embedding = face_info["embedding"]
#             bbox_xyxy = (x, y, x + w, y + h)  # Convert to xyxy format

#             face_data.append(
#                 ObjectDetection(
#                     label="face",
#                     confidence=float(confidence),
#                     bbox=[bbox_xyxy[0], bbox_xyxy[1], bbox_xyxy[2], bbox_xyxy[3]],
#                     embedding=embedding,
#                 )
#             )

#     except Exception as e:
#         print(f"DeepFace error in get_face_data_from_person_crop: {e}")
#     return face_data

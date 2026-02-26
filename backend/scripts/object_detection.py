import numpy as np

import cv2
from app_types import ObjectDetection
from ultralytics import YOLO
from insightface.app import FaceAnalysis

from auth.types import Person
import os


os.environ["TF_XLA_FLAGS"] = "--tf_xla_enable_xla_devices"

detect_model = YOLO("yolo11x.pt", task="detect", verbose=False)
classify_model = YOLO("yolo11x-cls.pt", task="classify", verbose=False)
print("Model loaded successfully.")

# Initialize once, not inside the function
face_app = FaceAnalysis(
    name="buffalo_l", providers=["CUDAExecutionProvider"]  # or ["CPUExecutionProvider"]
)

face_app.prepare(ctx_id=0)


def extract_object_from_image(image_path, whitelist: list[Person] = []):
    frame = cv2.imread(image_path)
    if frame is None:
        return [], []
    results = detect_model(frame, verbose=False)  # Adjust confidence and iou as needed

    objects = []
    people = []
    for r in results:
        boxes = r.boxes

        for box in boxes:
            x1, y1, x2, y2 = map(int, box.xyxy[0])

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
                    face_data = get_face_data_from_person_crop(frame[y1:y2, x1:x2])
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

                        label = "redacted face"
                        for whitelist_person in whitelist:
                            for embedding in whitelist_person.embeddings:
                                dist = np.array(embedding) @ np.array(face.embedding).T
                                if dist > 0.9:  # Adjust threshold as needed
                                    label = whitelist_person.name
                                    break

                        people.append(
                            ObjectDetection(
                                label=label,
                                confidence=face.confidence,
                                bbox=adjusted_bbox,
                                embedding=face.embedding,
                            )
                        )
    return objects, people


PERSON_CONF_THRESHOLD = 0.5


def get_face_data_from_person_crop(person_crop):
    """
    Detects faces in the person_crop, extracts aligned faces and their embeddings.
    Returns a list of ObjectDetection objects.
    """
    face_data = []

    try:
        faces = face_app.get(person_crop)
        for face in faces:
            confidence = float(face.det_score)

            if confidence < PERSON_CONF_THRESHOLD:
                continue

            x1, y1, x2, y2 = map(int, face.bbox)

            w = x2 - x1
            h = y2 - y1

            # Remove boxes that are same size as person crop
            size_diff = abs(w - person_crop.shape[1]) + abs(h - person_crop.shape[0])

            if size_diff < 10:
                continue

            embedding = face.embedding.tolist()

            face_data.append(
                ObjectDetection(
                    label="face",
                    confidence=confidence,
                    bbox=[x1, y1, x2, y2],
                    embedding=embedding,
                )
            )

    except Exception as e:
        print(f"InsightFace error in get_face_data_from_person_crop: {e}")

    return face_data

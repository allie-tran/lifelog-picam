import numpy as np

import cv2
from app_types import ObjectDetection
from ultralytics.models import YOLO
from insightface.app import FaceAnalysis

from auth.types import Person
import os

os.environ["TF_XLA_FLAGS"] = "--tf_xla_enable_xla_devices"

class ModelWrapper:
    def __init__(self):
        self.detect_model = None
        self.face_app = None
        self.loaded = False

    def load_models(self):
        if self.loaded:
            return
        self.detect_model = YOLO("yolo11x.pt", task="detect", verbose=False)
        self.face_app = FaceAnalysis(
            name="buffalo_l", providers=["CUDAExecutionProvider"]  # or ["CPUExecutionProvider"]
        )
        self.face_app.prepare(ctx_id=0)
        self.loaded = True

default_models_wrapper = ModelWrapper()

def extract_object_from_images(image_paths, whitelist: list[Person] = [], models_wrapper=default_models_wrapper):
    final_results = []
    if not models_wrapper.loaded:
        models_wrapper.load_models()

    assert models_wrapper.detect_model is not None, "Detection model failed to load"
    results = models_wrapper.detect_model(image_paths, verbose=False, conf=0.5)

    for i, r in enumerate(results):
        objects = []
        people = []
        frame = r.orig_img

        boxes = r.boxes
        for box in boxes:
            x1, y1, x2, y2 = map(int, box.xyxy[0])

            conf = box.conf[0]  # Confidence score
            cls = int(box.cls[0])
            class_name = models_wrapper.detect_model.names[cls]  # Get class name from model
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
                        rel_bbox=[x1 / w, y1 / h, x2 / w, y2 / h],
                    )
                )
                if class_name == "person":
                    face_data = get_face_data_from_person_crop(frame[y1:y2, x1:x2], models_wrapper=models_wrapper)
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
                        adjusted_bbox = [max(0, adjusted_bbox[0]), max(0, adjusted_bbox[1]), min(w, adjusted_bbox[2]), min(h, adjusted_bbox[3])]

                        label = "redacted face"
                        confidence = float(face.confidence)
                        for whitelist_person in whitelist:
                            for embedding in whitelist_person.embeddings:
                                embedding = np.array(embedding)
                                embedding = embedding / np.linalg.norm(embedding)  # Normalize the embedding
                                face_embedding = np.array(face.embedding)
                                face_embedding = face_embedding / np.linalg.norm(face_embedding)  # Normalize the face embedding
                                dist = np.dot(embedding, face_embedding)  # Cosine similarity
                                if dist > 0.8:  # Adjust threshold as needed
                                    confidence = dist
                                    label = whitelist_person.name
                                    break

                        people.append(
                            ObjectDetection(
                                label=label,
                                confidence=confidence,
                                bbox=adjusted_bbox,
                                rel_bbox=[
                                    adjusted_bbox[0] / w,
                                    adjusted_bbox[1] / h,
                                    adjusted_bbox[2] / w,
                                    adjusted_bbox[3] / h,
                                ],
                                embedding=face.embedding,
                            )
                        )
        final_results.append(
            {
                "image_path": image_paths[i],
                "objects": objects,
                "people": people,
            }
        )
    return final_results


PERSON_CONF_THRESHOLD = 0.5

def get_face_data_from_person_crop(person_crop, models_wrapper=default_models_wrapper):
    """
    Detects faces in the person_crop, extracts aligned faces and their embeddings.
    Returns a list of ObjectDetection objects.
    person_crop: numpy array of the cropped person image
    """
    face_data = []
    if not models_wrapper.loaded:
        models_wrapper.load_models()
    assert models_wrapper.face_app is not None, "Face analysis model failed to load"

    try:
        faces = models_wrapper.face_app.get(person_crop)
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

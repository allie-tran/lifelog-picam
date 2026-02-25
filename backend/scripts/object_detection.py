import numpy as np

import cv2
from app_types import ObjectDetection
from ultralytics import YOLO
from deepface import DeepFace

from auth.types import Person

detect_model = YOLO('yolo11x.pt', task='detect', verbose=False)
classify_model = YOLO('yolo11x-cls.pt', task='classify', verbose=False)
print("Model loaded successfully.")

def extract_object_from_image(
    image_path,
    whitelist: list[Person] = []
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

                        label = "redacted face"
                        for whitelist_person in whitelist:
                            for embedding in whitelist_person.embeddings:
                                dist = np.array(embedding) @ np.array(face.embedding).T
                                if dist > 0.9:  # Adjust threshold as needed
                                    label = whitelist_person.name
                                    break

                        people.append(ObjectDetection(
                            label=label,
                            confidence=face.confidence,
                            bbox=adjusted_bbox,
                            embedding=face.embedding,
                        ))
    return objects, people

PERSON_CONF_THRESHOLD = 0.5

def get_face_data_from_person_crop(person_crop):
    """
    Detects faces in the person_crop, extracts aligned faces and their embeddings.
    Returns a list of dictionaries: [{'embedding': [], 'bbox': (x1,y1,x2,y2)}]
    """
    face_data = []
    try:
        faces = DeepFace.represent(
            img_path=person_crop,
            model_name="Facenet512",
            enforce_detection=False,
            detector_backend="yolov8",
            normalization="Facenet2018",
        )

        for face_info in faces:
            confidence = face_info["face_confidence"]
            if confidence < PERSON_CONF_THRESHOLD:
                continue

            face = face_info["facial_area"]
            x, y, w, h = (
                face["x"],
                face["y"],
                face["w"],
                face["h"],
            )
            # Remove box that are the same size (or similar) as the person crop
            size_diff = abs(w - person_crop.shape[1]) + abs(h - person_crop.shape[0])
            if size_diff < 10:  # Adjust threshold as needed
                continue

            embedding = face_info["embedding"]
            bbox_xyxy = (x, y, x + w, y + h)  # Convert to xyxy format

            face_data.append(
                ObjectDetection(
                    label="face",
                    confidence=float(confidence),
                    bbox=[bbox_xyxy[0], bbox_xyxy[1], bbox_xyxy[2], bbox_xyxy[3]],
                    embedding=embedding,
                )
            )

    except Exception as e:
        print(f"DeepFace error in get_face_data_from_person_crop: {e}")
    return face_data

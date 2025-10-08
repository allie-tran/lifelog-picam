# You can install it using pip:
# pip install ultralytics

import json
import os
import glob
from typing import Any
from tqdm import tqdm


import cv2
from ultralytics import YOLO

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
                    {
                        "class": class_name,
                        "confidence": float(conf),
                        "bbox": [x1, y1, x2, y2],
                    }
                )
                people.append(
                    {
                        "confidence": float(conf),
                        "bbox": [x1, y1, x2, y2],
                    }
                )
    return objects, people

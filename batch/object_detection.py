from typing import List, Optional

from PIL.Image import Image
from deepface import DeepFace
from pydantic import BaseModel
from tqdm import tqdm
from ultralytics.models import YOLO
from datetime import datetime

import os
from PIL import Image, ImageFilter, ImageDraw

DIR = f"/mnt/ssd0/LifelogPicam"
THUMBNAIL_DIR = f"/mnt/ssd0/Images/LifelogPicam"

class ObjectDetection(BaseModel):
    label: str
    confidence: float
    bbox: list[int]  # [x_min, y_min, x_max, y_max]
    embedding: Optional[list[float]] = None


detect_model = YOLO("yolo11x.pt", task="detect", verbose=False)
print("Model loaded successfully.")

def extract_object_from_image(image_paths, frames):
    final_results = []
    results = detect_model(image_paths, verbose=False)  # Adjust confidence and iou as needed

    for r in results:
        path = r.path
        objects = []
        people = []
        frame = frames.get(path)
        if frame is None:
            print(f"Error reading image: {path}")
            continue

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
                        people.append(
                            ObjectDetection(
                                label="face",
                                confidence=face.confidence,
                                bbox=adjusted_bbox,
                                embedding=face.embedding,
                            )
                        )
        final_results.append(
            {
                "image_path": path,
                "objects": objects,
                "people": people,
            }
        )
    return final_results


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

if __name__ == "__main__":
    import glob

    from pymongo import MongoClient
    from tqdm import tqdm

    client = MongoClient("mongodb://localhost:27017/")
    db = client["picam"]
    images = db["images"]
    device = "cathal"
    all_indexed = images.aggregate(
        [{"$match": {"device": device}}, {"$group": {"_id": "$image_path"}}]
    )
    all_indexed = set(record["_id"] for record in all_indexed)

    CURRENT_DIR = f"{DIR}/{device}"
    all_images_on_files = glob.glob(f"{CURRENT_DIR}/**/*.jpg", recursive=True)
    all_images_on_files = [img.replace(CURRENT_DIR + "/", "") for img in all_images_on_files]
    all_images_on_files = set(all_images_on_files)

    non_existing_images = all_images_on_files - all_indexed
    print(f"Number of images on files: {len(all_images_on_files)}")
    print(f"Number of indexed images: {len(all_indexed)}")
    print(f"Number of non-indexed images: {len(non_existing_images)}")
    non_existing_images = list(non_existing_images)
    non_existing_images = sorted(non_existing_images)

    batch_size = 32
    new_collection = db["images"]
    for i in tqdm(range(0, len(non_existing_images), batch_size)):
        batch_paths = non_existing_images[i : i + batch_size]
        batch_full_paths = [f"{CURRENT_DIR}/{path}" for path in batch_paths]

        frames = {}
        for path in batch_full_paths:
            try:
                Image.open(path).verify()  # Verify that the image can be opened
            except Exception as e:
                print(f"Error reading image {path}: {e}")
                continue

        if not frames:
            continue

        results = extract_object_from_image(list(frames.keys()), frames)

        for result in results:
            path = result["image_path"].replace(CURRENT_DIR + "/", "")
            time = datetime.strptime(path.split("/")[1], "%Y%m%d_%H%M%S.jpg")
            if result["people"]:
                blur_image(result["image_path"], result["people"])
            else:
                compress_image(result["image_path"])

            try:
                new_collection.insert_one(
                    {
                        "date": path.split("/")[0],
                        "device": device,
                        "image_path": path,
                        "thumbnail": path.replace(".jpg", ".webp"),
                        "timestamp": time.timestamp() * 1000,
                        "is_video": False,
                        "objects": [obj.model_dump() for obj in result["objects"]],
                        "people": [person.model_dump() for person in result["people"]],
                        "processed": {"yolo": True, "encoded": True},
                    }
                )
            except Exception as e:
                print(f"Error inserting document for {path}: {e}")
                continue

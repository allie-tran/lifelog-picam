import os
import traceback

import cv2
import numpy as np
import torch
from dotenv import load_dotenv
from PIL import Image, ImageDraw
from sqlalchemy import Row, create_engine, select
from sqlalchemy.orm import Session, selectinload
from tqdm import tqdm

from models import Image as ImageModel

load_dotenv()
MASK_DIRS = [
    "/mnt/ssd0/embeddings/masks/masks",
    "/mnt/ssd0/embeddings/masks/extra_masks",
    "/mnt/ssd0/embeddings/masks/documents",
]
PG_URI = os.getenv("PG_URI")  # Your PostgreSQL connection string
DIR = os.getenv(
    "DIR", "/mnt/ssd0/LifelogPicam"
)  # Directory containing original images
THUMBNAIL_DIR = os.getenv(
    "THUMBNAIL_DIR", "/mnt/ssd0/Images/LifelogPicam"
)  # Directory to save thumbnails
assert PG_URI is not None, "PG_URI environment variable is not set"


def blur_image_mosaic(image, mask, scale_ratio=0.05):
    """
    Calculates hexagon size based mask area
    0.05 means for each mask area there are 20 hexagons
    """
    h, w = image.shape[:2]

    # Calculate the area of the mask
    mask_area = np.count_nonzero(mask)
    total_area = h * w
    mask_ratio = mask_area / total_area

    # Determine hexagon size based on the mask ratio
    size = max(10, int(min(h, w) * scale_ratio * np.sqrt(mask_ratio)))
    size = min(size, 50)  # Cap the size to prevent excessively large hexagons

    # Constants for hexagonal geometry
    v_step = int(size * 1.5)
    h_step = int(size * np.sqrt(3))

    # Create a blank output image
    output = image.copy()

    # Make the mask bigger to ensure we cover the edges properly
    mask = cv2.dilate(mask.astype(np.uint8), np.ones((size, size), np.uint8), iterations=1).astype(bool)
    # Create a grid of points
    for y in range(0, h + v_step, v_step):
        # Shift every other row to create the honeycomb stagger
        offset = (h_step // 2) if (y // v_step) % 2 else 0

        for x in range(-offset, w + h_step, h_step):
            # 1. Define the 6 points of the hexagon
            points = []
            for i in range(6):
                angle_deg = 60 * i - 30
                angle_rad = np.pi / 180 * angle_deg
                px = int(x + size * np.cos(angle_rad))
                py = int(y + size * np.sin(angle_rad))
                points.append([px, py])

            poly = np.array([points], dtype=np.int32)

            # 2. Check if this hexagon overlaps with our SAM mask
            # We check the center point for speed
            cx, cy = np.clip(x, 0, w - 1), np.clip(y, 0, h - 1)
            if mask[cy, cx]:
                # 3. Get the average color from the original image at the center
                color = image[cy, cx].tolist()
                # 4. Draw the filled hexagon onto the output
                cv2.fillPoly(output, poly, color)  # type: ignore

    # only apply the masked areas, keep the rest of the image intact
    output = np.where(mask[:, :, None], output, image)
    return output


def normal_blur(image, mask, ksize=51):
    # Apply a strong Gaussian blur to the entire image
    blurred = cv2.GaussianBlur(image, (ksize, ksize), 0)

    # Combine the blurred and original images using the mask
    output = np.where(mask[:, :, None], blurred, image)
    return output


def create_blur_mask(boxes, image_height, image_width, oval=True):
    full_mask = Image.new(
        "L", (image_width, image_height), 0
    )  # Initialize an empty mask
    for box in boxes:
        x1, y1, x2, y2 = box
        x1, y1, x2, y2 = int(x1), int(y1), int(x2), int(y2)

        # expand box by 10%
        box_width = x2 - x1
        box_height = y2 - y1
        x1 = max(0, int(x1 - box_width * 0.1))
        y1 = max(0, int(y1 - box_height * 0.1))
        x2 = min(image_width, int(x2 + box_width * 0.1))
        y2 = min(image_height, int(y2 + box_height * 0.1))

        try:
            if oval:
                # Paste in an oval
                mask = Image.new("L", (box_width, box_height), 0)
                draw = ImageDraw.Draw(mask)
                draw.ellipse(
                    [(0, 0), (box_width, box_height)],
                    fill=255,
                )
                full_mask.paste(mask, (x1, y1), mask)
            else:
                # Paste in a rectangle
                mask = Image.new("L", (box_width, box_height), 255)
                full_mask.paste(mask, (x1, y1), mask)
        except Exception as e:
            print(f"Error blurring region ({x1}, {y1}, {x2}, {y2}): {e}")
            continue

    # Convert to boolean mask
    return np.array(full_mask).astype(bool)

def create_polygon_mask(polygons, image_height, image_width):
    full_mask = Image.new(
        "L", (image_width, image_height), 0
    )  # Initialize an empty mask
    for points in polygons:
        try:
            # Create a polygon mask
            mask = Image.new("L", (image_width, image_height), 0)
            draw = ImageDraw.Draw(mask)
            draw.polygon(points, fill=255)

            full_mask.paste(mask, (0, 0), mask)
        except Exception as e:
            print(f"Error blurring region ({points}): {e}")
            continue

    # Convert to boolean mask
    return np.array(full_mask).astype(bool)

def anonymise_image(
    relative_path,
    image_path,
    thumbnail_path,
    face_boxes,
    annotation_points,
    quality=100,
):
    # Process results
    original = Image.open(image_path)
    img = cv2.imread(image_path)
    assert img is not None, f"Failed to read image {image_path}"
    full_mask = create_blur_mask(face_boxes, img.shape[0], img.shape[1], oval=True)
    # convert polygon annotation to actual size (from percentage to pixels)
    annotation_polygons = []
    for annotation in annotation_points:
        polygon = []
        for point in annotation:
            x = int(point[0] * img.shape[1])
            y = int(point[1] * img.shape[0])
            polygon.append((x, y))
        annotation_polygons.append(polygon)
    annotation_mask = create_polygon_mask(annotation_polygons, img.shape[0], img.shape[1])
    full_mask |= annotation_mask

    for MASK_DIR in MASK_DIRS:
        mask_path = os.path.join(
            MASK_DIR, os.path.splitext(relative_path)[0] + ".npz"
        )
        if os.path.exists(mask_path):
            sam3_mask = np.load(mask_path)["mask"]
            sam3_mask = sam3_mask.astype(bool)
            full_mask |= sam3_mask

    # Apply mosaic blur to the original image using the combined mask
    anonymised_image = blur_image_mosaic(img, full_mask)
    # anonymised_image = normal_blur(img, full_mask)
    os.makedirs(os.path.dirname(thumbnail_path), exist_ok=True)
    # 4. Resize to max 800x800 while maintaining aspect ratio
    anonymised_image = cv2.cvtColor(
        anonymised_image, cv2.COLOR_BGR2RGB
    )  # Convert to RGB for PIL
    img = Image.fromarray(anonymised_image)
    img.thumbnail((1080, 1080))
    ori_exif = original.getexif()
    img.save(thumbnail_path, "WEBP", quality=quality, exif=ori_exif)


def check_date(date_str):
    if date_str == "2019-01-01":
        return True
    return False
    year, month, day = date_str.split("-")
    # if year == "2021":
    #     return True
    # if year == "2022" and int(month) > 6:
    #     return True
    if year == "2020" and int(month) == 6:
        return True
    return False


if __name__ == "__main__":
    DEVICE = "cathal"
    print("Scanning directories for images and thumbnails...")
    dates = sorted(os.listdir(f"{DIR}/{DEVICE}"))

    print(f"Found {len(dates)} dates to process.")
    engine = create_engine(PG_URI)
    for date in dates:
        if not check_date(date):
            continue

        print(f"Processing date: {date}")
        original_images = os.listdir(os.path.join(DIR, DEVICE, date))
        original_images = set(
            image for image in original_images if image.endswith(".jpg")
        )

        with Session(engine) as session:
            images = (
                session.execute(
                    select(ImageModel)
                    .options(
                        selectinload(ImageModel.people), selectinload(ImageModel.annotations)
                    )
                    .where(ImageModel.device == DEVICE, ImageModel.date == date)
                    .order_by(ImageModel.timestamp.asc())
                )
                .scalars()
                .all()
            )

            pbar = tqdm(total=len(images), desc=f"Processing {date}")
            for image in images:
                pbar.update(1)
                pbar.set_postfix({"image": image.image_path})
                try:
                    date = image.date
                    people = image.people
                    face_boxes = []
                    for person in people:
                        face_boxes.append(person.bbox)

                    anonymise_image(
                        image.image_path,
                        os.path.join(DIR, DEVICE, image.image_path),
                        os.path.join(THUMBNAIL_DIR, DEVICE, image.thumbnail),
                        face_boxes,
                        [annotation.points for annotation in image.annotations],
                        quality=100,
                    )
                except Exception as e:
                    print(f"Error processing image {image.image_path}: {e}")
                    traceback.print_exc()
                    continue

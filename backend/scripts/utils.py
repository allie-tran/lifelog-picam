import base64
import os
from typing import List

from app_types import ObjectDetection
from constants import DIR, THUMBNAIL_DIR
from PIL import Image, ImageDraw, ImageFilter

os.makedirs(THUMBNAIL_DIR, exist_ok=True)


def to_base64(image_data: bytes) -> str:
    """Convert image data to base64 string."""
    return base64.b64encode(image_data).decode("utf-8")


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


def make_video_thumbnail(video_path):
    rel_path = video_path.replace(DIR + "/", "")
    output_path = f"{THUMBNAIL_DIR}/{rel_path.rsplit('.', 1)[0]}.webp"
    if os.path.exists(output_path):
        return output_path

    os.makedirs(os.path.dirname(output_path), exist_ok=True)
    status = os.system(
        f"ffmpeg -y -i '{video_path}' -ss 00:00:01.000 -vframes 1 -vf 'scale=800:-1' '{output_path}'"
    )
    if status != 0:
        print("Failed to generate thumbnail for video:", video_path)
        os.remove(output_path) if os.path.exists(output_path) else None
        return None
    return output_path

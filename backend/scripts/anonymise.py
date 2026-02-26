import gc  # Garbage collector
import colorsys
import os

import cv2
import numpy as np
import torch
from PIL import Image, ImageDraw
from ultralytics import SAM
from ultralytics.models.sam import SAM3SemanticPredictor

from scripts.utils import to_base64

# Initialize predictor with configuration
overrides = dict(
    conf=0.25,
    task="segment",
    mode="predict",
    model="sam3.pt",
    half=True,  # Use FP16 for faster inference
    save=False,
    verbose=False,
    imgsz=644,  # Set to a multiple of 14 to stop the warning
)
sam3 = SAM3SemanticPredictor(overrides=overrides)

import cv2
import numpy as np


def blur_image_mosaic(image, mask, scale_ratio=0.0075):
    """
    Calculates hexagon size based on image resolution.
    """
    h, w = image.shape[:2]

    # 1. Calculate image diagonal for scale
    diagonal = np.sqrt(h**2 + w**2)

    # 2. Set size (radius) as a percentage of that diagonal
    size = int(diagonal * scale_ratio)
    size = max(4, size)  # Safety minimum

    # Constants for hexagonal geometry
    v_step = int(size * 1.5)
    h_step = int(size * np.sqrt(3))

    # Constants for hexagonal geometry
    # Height of a triangle in the hexagon
    v_step = int(size * 1.5)
    h_step = int(size * np.sqrt(3))

    # Create a blank output image
    output = image.copy()

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
    # output = np.where(mask[:, :, None], output, image)
    return output


def create_blur_mask(boxes, image_height, image_width):
    full_mask = Image.new(
        "L", (image_width, image_height), 0
    )  # Initialize an empty mask
    for box in boxes:
        x1, y1, x2, y2 = box

        # expand box by 10%
        box_width = x2 - x1
        box_height = y2 - y1
        x1 = max(0, int(x1 - box_width * 0.1))
        y1 = max(0, int(y1 - box_height * 0.1))
        x2 = min(image_width, int(x2 + box_width * 0.1))
        y2 = min(image_height, int(y2 + box_height * 0.1))

        try:
            # Paste in an oval
            mask = Image.new("L", (box_width, box_height), 0)
            draw = ImageDraw.Draw(mask)
            draw.ellipse(
                [(0, 0), (box_width, box_height)],
                fill=255,
            )
            full_mask.paste(mask, (x1, y1), mask)
        except Exception as e:
            print(f"Error blurring region ({x1}, {y1}, {x2}, {y2}): {e}")
            continue

    # Convert to boolean mask
    return np.array(full_mask).astype(bool)


ALL_PRIVATE_LABELS = [
    "face",
    "face with glasses or masks",
    "screen content (e.g. computer screen, phone screen, tablet screen)",
    "private document (e.g. bank statement, tax document, medical record, passport, visa, id card)",
    "home address (e.g. on a letter, package, or document)",
    "license plate",
    "signature",
    "cards (e.g. credit card, id card, bank card)",
]


def anonymise_image(image_path, thumbnail_path, boxes, whitelist_boxes, quality=80):
    # Process results
    img = cv2.imread(image_path)
    assert img is not None, f"Failed to read image {image_path}"
    full_mask = create_blur_mask(boxes, img.shape[0], img.shape[1])
    try:
        sam3.set_image(image_path)

        batch_size = 4
        # Query with multiple text prompts
        with torch.no_grad():  # Disable gradients for inference
            for i in range(0, len(ALL_PRIVATE_LABELS), batch_size):
                batch_labels = ALL_PRIVATE_LABELS[i : i + batch_size]
                results = sam3(
                    text=batch_labels,
                    stream=True,
                )

                for result in results:
                    result = result.cpu()  # Move to CPU for processing
                    if result.masks is not None:
                        mask = result.masks.data.any(dim=0).numpy().astype(bool)
                        # check if the mask has too much overlapping with the whitelist areas, if so, skip it
                        to_blur = True
                        for bbox in whitelist_boxes:
                            if mask[bbox[1] : bbox[3], bbox[0] : bbox[2]].any():
                                overlap_area = np.sum(
                                    mask[bbox[1] : bbox[3], bbox[0] : bbox[2]]
                                )
                                bbox_area = (bbox[2] - bbox[0]) * (bbox[3] - bbox[1])
                                if overlap_area / bbox_area > 0.8:
                                    to_blur = False
                                    break
                        if to_blur:
                            full_mask |= mask  # Combine masks using logical OR
                        del mask

        # full_mask = np.zeros(img.shape[:2], dtype=bool)  # Initialize an empty mask
        sam3.reset_image()
        # Remove whitelist areas from the mask
        for bbox in whitelist_boxes:
            x1, y1, x2, y2 = bbox
            full_mask[y1:y2, x1:x2] = False

    except torch.cuda.OutOfMemoryError:
        print(f"CUDA Out of Memory while processing {image_path}. Skipping.")

    # Apply mosaic blur to the original image using the combined mask
    anonymised_image = blur_image_mosaic(img, full_mask)
    # just block out the areas for now with red
    # img[full_mask] = [0, 0, 255]
    # anonymised_image = img

    if "results" in locals():
        del results

    gc.collect()
    torch.cuda.empty_cache()
    sam3.reset_image()

    os.makedirs(os.path.dirname(thumbnail_path), exist_ok=True)
    # 4. Resize to max 800x800 while maintaining aspect ratio
    anonymised_image = cv2.cvtColor(
        anonymised_image, cv2.COLOR_BGR2RGB
    )  # Convert to RGB for PIL
    img = Image.fromarray(anonymised_image)
    img.thumbnail((1080, 1080))
    img.save(thumbnail_path, "WEBP", quality=quality)


model = SAM("sam3.pt")

def get_colors(N: int):
    HSV_tuples = [(x*1.0/N, 0.5, 0.5) for x in range(N)]
    RGB_tuples = map(lambda x: colorsys.hsv_to_rgb(*x), HSV_tuples)
    return [(int(r*255), int(g*255), int(b*255)) for r, g, b in RGB_tuples]

def segment_image_with_sam(image):
    # get the middle point
    points = np.array([[image.width // 2, image.height // 2]])
    results = model.predict(image, verbose=False, stream=True, points=points, labels=[1])
    image = np.array(image.convert("RGB"))
    mask_list = []
    bbox_list = []
    for result in results:
        if result.masks is None:
            continue

        # 2. Logic to find the "Biggest" mask
        # result.masks.data is a tensor of shape [N, H, W]
        result = result.cpu()  # Move to CPU for processing
        all_masks = result.masks.data.numpy()
        all_colors = get_colors(all_masks.shape[0])
        for i, mask in enumerate(all_masks):
            coords = np.argwhere(mask > 0)
            if len(coords) == 0:
                continue

            y_c, x_c = coords.mean(axis=0).astype(int)
            cv2.circle(image, (x_c, y_c), 15, all_colors[i], -1)
            cv2.putText(
                image,
                str(i),
                (x_c - 10, y_c + 5),
                cv2.FONT_HERSHEY_SIMPLEX,
                0.6,
                (255, 255, 255),
                2,
            )

            # Overlay the mask on the image for visualization
            color_mask = np.zeros_like(image)
            color_mask[mask > 0] = all_colors[i]
            alpha = 0.7
            image = cv2.addWeighted(image, 1, color_mask, alpha, 0)


            # Save the mask as a PNG in memory and convert to base64
            _, mask_buffor = cv2.imencode(".png", mask.astype(np.uint8) * 255)
            mask_list.append(to_base64(mask_buffor))

            bbox = cv2.boundingRect(mask.astype(np.uint8))
            bbox_list.append(bbox)

        # Convert RGB to BGR for OpenCV
        bgr_img = cv2.cvtColor(image, cv2.COLOR_RGB2BGR)
        _, buffer = cv2.imencode(".jpg", bgr_img)

        return to_base64(buffer), mask_list, bbox_list

    return None, [], []

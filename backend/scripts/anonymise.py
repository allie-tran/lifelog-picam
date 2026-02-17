from ultralytics.models.sam import SAM3SemanticPredictor
import cv2
import gc  # Garbage collector
import numpy as np
import torch
from PIL import Image
import os

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
                cv2.fillPoly(output, poly, color)

    return output


def anonymise_image(image_path, thumbnail_path, quality=80):
    sam3.set_image(image_path)

    # Query with multiple text prompts
    results = sam3(
        text=[
            "screen",
            "face",
            "document",
            "address",
            "license plate",
            "signature",
            "name plate",
            "credit card",
            "bank card",
            "id card",
            "passport",
            "vehicle registration",
            "social security number",
            "barcode",
            "qr code",
        ]
    )

    # Process results
    img = cv2.imread(image_path)
    full_mask = np.zeros(img.shape[:2], dtype=bool)  # Initialize an empty mask
    for result in results:
        mask = result.masks.data.any(dim=0).cpu().numpy().astype(bool)
        full_mask |= mask  # Combine masks using logical OR

    # Apply mosaic blur to the original image using the combined mask
    anonymised_image = blur_image_mosaic(img, full_mask)

    # 3. Explicit Cleanup
    del results
    gc.collect()  # Python overhead cleanup
    torch.cuda.empty_cache()  # GPU memory release

    os.makedirs(os.path.dirname(thumbnail_path), exist_ok=True)
    # 4. Resize to max 800x800 while maintaining aspect ratio
    anonymised_image = cv2.cvtColor(anonymised_image, cv2.COLOR_BGR2RGB)  # Convert to RGB for PIL
    img = Image.fromarray(anonymised_image)
    img.thumbnail((800, 800))
    img.save(thumbnail_path, "WEBP", quality=quality)

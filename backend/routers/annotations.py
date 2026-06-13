
from datetime import datetime, timezone
from typing import Annotated, List
from PIL import ImageDraw, Image
import cv2
import numpy as np
from fastapi import Depends, APIRouter, HTTPException, UploadFile
from sqlalchemy import insert, select
from sqlalchemy.orm import Session

from auth import _require_owner
from auth.auth_models import auth_dependency
from auth.types import AccessLevel
from core.config import THUMBNAIL_DIR
from database import get_session
from database.models import AnnotationType, Image as ImageModel, Annotation
from core.dependencies import CamelCaseModel
from services.anonymise import blur_image_gaussian, segment_image_with_sam


router = APIRouter()
@router.get("/health")
def health_check():
    return {"status": "ok"}

# ---------------------------------------------------------------------------
# Annotations
# ---------------------------------------------------------------------------

class AnnotationUpdate(CamelCaseModel):
    image_path: str
    points: List[tuple[float, float]]
    label: str
    author: str

@router.post("/add-annotation")
def add_annotation(
    device: str,
    annotation: AnnotationUpdate,
    access_level: Annotated[AccessLevel, Depends(auth_dependency)] = AccessLevel.NONE,
    session: Session = Depends(get_session),
):
    _require_owner(access_level)

    image_record = session.execute(
        select(ImageModel).where(ImageModel.image_path == annotation.image_path).where(ImageModel.device == device)
    ).scalar_one_or_none()

    if image_record is None:
        raise HTTPException(status_code=404, detail="Image not found")

    stmt = insert(Annotation).values(
        image_id=image_record.id,
        points=annotation.points,
        label=annotation.label,
        author=annotation.author,
        timestamp=datetime.now(timezone.utc),
        anno_type=AnnotationType.POLYGON,
    )
    session.execute(stmt)
    session.commit()

    thumbnail_path = f"{THUMBNAIL_DIR}/{device}/{image_record.thumbnail}"
    thumbnail_image = Image.open(thumbnail_path).convert("RGB")
    mask = Image.new("L", thumbnail_image.size, 0)
    draw = ImageDraw.Draw(mask)
    actual_points = []

    for x, y in annotation.points:
        actual_x = int(x * thumbnail_image.width)
        actual_y = int(y * thumbnail_image.height)
        actual_points.append((actual_x, actual_y))

    draw.polygon(actual_points, fill=255)
    exif = thumbnail_image.getexif()

    # convert to cv2
    thumbnail_image = cv2.cvtColor(np.array(thumbnail_image), cv2.COLOR_RGB2BGR)
    mask = np.array(mask)
    output = blur_image_gaussian(
        thumbnail_image,
        mask,
    )
    # save output to thumbnail path
    output_image = Image.fromarray(cv2.cvtColor(output, cv2.COLOR_BGR2RGB))
    output_image.save(thumbnail_path, exif=exif)

    return {"message": "Annotation added successfully."}

# ---------------------------------------------------------------------------
# Image segmentation
# ---------------------------------------------------------------------------
@router.post("/segment-image")
def segment_image(file: UploadFile):
    visualised_base64, masks_data, bbox_list = segment_image_with_sam(
        Image.open(file.file)
    )
    return {
        "visualisation": f"data:image/jpeg;base64, {visualised_base64}",
        "masks": masks_data,
        "bboxes": bbox_list,
    }

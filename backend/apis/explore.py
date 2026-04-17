import base64
from PIL import Image
import io
import os
from fastapi import Depends, FastAPI, HTTPException

from fastapi import Depends, HTTPException
from sqlalchemy import  func,   case
from sqlalchemy.orm import Session

from app_types.general import LocationInfo
from auth.auth_models import auth_dependency
from auth.types import AccessLevel
from auth import _require_owner


from sqlalchemy import select, desc
from typing import Annotated, Any

from constants import DIR
from database import get_session
from database.models import Image as ImageModel, ImagePerson, Location
from app_types import CamelCaseModel
from scripts.utils import to_absolute_bbox

app = FastAPI()

@app.get("/health")
def health_check():
    return {"status": "ok"}


class ValuesRequest(CamelCaseModel):
    field: str
    extra_params: dict[str, Any] = {}

@app.post("/get-locations")
def get_locations(
    device: str,
    request: ValuesRequest,
    access_level: Annotated[AccessLevel, Depends(auth_dependency)] = AccessLevel.NONE,
    session: Session = Depends(get_session),
):
    _require_owner(access_level)
    extra_params = request.extra_params

    country_filter = extra_params.get("country")
    display_name = case(
        (Location.name.in_(["---", "Unknown Place", ""]), Location.address),
        else_=Location.name
    ).label("display_name")

    stmt = (
        select(Location, display_name)
        .join(ImageModel, ImageModel.location_id == Location.id)
        .where(ImageModel.device == device)
        .where(Location.stop == True)
    )
    if country_filter:
        stmt = stmt.where(Location.country.in_(country_filter))

    stmt = (stmt
        .group_by(Location.id)
        .order_by(desc(func.count(ImageModel.id))) # Sort by most images
        .limit(20)
    )

    res = session.execute(stmt).fetchall()

    locations = []
    for loc, display_name in res:
        loc_info = LocationInfo.model_validate(loc.__dict__)
        loc_info.name = display_name
        locations.append(loc_info)

    return locations

@app.post("/available-values")
def available_values(
    device: str,
    request: ValuesRequest,
    access_level: Annotated[AccessLevel, Depends(auth_dependency)] = AccessLevel.NONE,
    session: Session = Depends(get_session),
):
    _require_owner(access_level)
    field = request.field
    extra_params = request.extra_params
    print(f"Getting available values for field: {field} and device: {device}")
    print(f"Extra params: {extra_params}")
    match field:
        case "person":
            stmt = (
                select(ImagePerson.label).join(ImageModel, ImageModel.id == ImagePerson.image_id).where(ImageModel.device == device).distinct()
            )
        case "location":
            display_name = case(
                (Location.name.in_(["---", "Unknown Place", ""]), Location.address),
                else_=Location.name
            ).label("display_name")

            countries = extra_params.get("country", [])
            stmt = (select(display_name)
                .join(ImageModel, ImageModel.location_id == Location.id)
                .where(ImageModel.device == device)
            )
            if countries:
                stmt = stmt.where(Location.country.in_(countries))

            stmt = (stmt
                .group_by(display_name)
                .order_by(desc(func.count(ImageModel.id))) # Sort by most images
                .limit(20)
            )
        case "country":
            stmt = (
                select(Location.country)
                .join(ImageModel, ImageModel.location_id == Location.id)
                .where(ImageModel.device == device)
                .group_by(Location.country)
                .order_by(desc(func.count(ImageModel.id))) # Sort by most images
                .where(Location.country != None, Location.country != "")
                .where(Location.stop == True)
                .limit(20)
            )
        case "year":
            stmt = select(ImageModel.year).where(ImageModel.device == device).distinct()

        case _:
            raise HTTPException(status_code=400, detail="Invalid field name.")
    results = session.execute(stmt).fetchall()
    return [r[0] for r in results]

@app.get("/all-faces")
def get_all_faces(
    device: str,
    access_level: Annotated[AccessLevel, Depends(auth_dependency)] = AccessLevel.NONE,
    session: Session = Depends(get_session),
):
    _require_owner(access_level)
    stmt = select(ImagePerson.label).join(ImageModel, ImageModel.id == ImagePerson.image_id).where(ImageModel.device == device).distinct()
    results = session.execute(stmt).fetchall()

    faces = []

    # get actual images for each person
    for r in results:
        face = {
            "name": r[0],
            "images": [],
        }
        # select randomly 2 images for this person
        stmt = (
            select(ImagePerson.bbox, ImageModel.image_path)
            .join(ImageModel, ImageModel.id == ImagePerson.image_id)
            .where(ImageModel.device == device, ImagePerson.confidence > 0.8)
            .where(ImagePerson.label == r[0])
            .limit(2)
        )
        images = session.execute(stmt).fetchall()
        # get cropped images for each bbox
        cropped = []
        for bbox, image_path in images:
            image_full_path = os.path.join(DIR, device, image_path)
            if os.path.exists(image_full_path):
                img = Image.open(image_full_path)
                print(img.size, bbox)
                bbox = to_absolute_bbox(bbox, img.width, img.height)
                x1, y1, x2, y2 = bbox
                print(f"Cropping image {image_path} with bbox {bbox} for face {r[0]}")
                cropped_img = img.crop(bbox)
                buf = io.BytesIO()
                cropped_img.save(buf, format="JPEG")
                cropped.append(base64.b64encode(buf.getvalue()).decode("utf-8"))
                face["images"].append(f"data:image/jpeg;base64, {cropped[-1]}")
        faces.append(face)
    return faces

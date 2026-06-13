import base64
import logging
import time
from functools import lru_cache
from PIL import Image
import io
import os
from fastapi import Depends, APIRouter, HTTPException, Query
from sqlalchemy import func, case, or_, select, desc
from sqlalchemy.orm import Session

from schemas.general import LocationInfo
from auth.auth_models import auth_dependency
from auth.types import AccessLevel
from auth import _require_owner
import numpy as np

from typing import Annotated, Any

from core.config import DIR, THUMBNAIL_DIR
from database import get_session
from database.models import Device, Image as ImageModel, ImagePerson, Location, PeopleCluster
from schemas import CamelCaseModel
from services.utils import to_absolute_bbox

router = APIRouter()
logger = logging.getLogger(__name__)

# Simple in-process TTL cache for /all-faces — avoids re-cropping images on
# every FacesScreen reload. Keyed by device; expires after 5 minutes.
_FACES_CACHE: dict[str, tuple[float, list]] = {}
_FACES_TTL = 300  # seconds


@router.get("/health")
def health_check():
    return {"status": "ok"}


class ValuesRequest(CamelCaseModel):
    field: str
    extra_params: dict[str, Any] = {}

def _location_display_name():
    return case(
        (Location.name.in_(["---", "Unknown Place", ""]), Location.address),
        else_=Location.name
    ).label("display_name")


def _locations_to_info(res) -> list[LocationInfo]:
    locations = []
    for loc, display_name, img_count in res:
        loc_info = LocationInfo.model_validate(loc.__dict__)
        loc_info.name = display_name
        loc_info.id = str(loc_info.id)
        loc_info.count = img_count
        locations.append(loc_info)
    return locations


@router.post("/get-locations")
def get_locations(
    device: str,
    request: ValuesRequest,
    access_level: Annotated[AccessLevel, Depends(auth_dependency)] = AccessLevel.NONE,
    session: Session = Depends(get_session),
):
    _require_owner(access_level)
    extra_params = request.extra_params

    country_filter = extra_params.get("country")
    img_count = func.count(ImageModel.id).label("img_count")

    stmt = (
        select(Location, _location_display_name(), img_count)
        .join(ImageModel, ImageModel.location_id == Location.id)
        .where(ImageModel.device == device)
        .where(Location.stop == True)
    )
    if country_filter:
        stmt = stmt.where(Location.country.in_(country_filter))

    stmt = (stmt
        .group_by(Location.id)
        .order_by(desc(img_count))
        .limit(20)
    )

    return _locations_to_info(session.execute(stmt).fetchall())


@router.get("/search-locations")
def search_locations(
    device: str,
    q: str,
    limit: int = Query(default=20, le=50),
    access_level: Annotated[AccessLevel, Depends(auth_dependency)] = AccessLevel.NONE,
    session: Session = Depends(get_session),
):
    _require_owner(access_level)

    pattern = f"%{q}%"
    img_count = func.count(ImageModel.id).label("img_count")

    stmt = (
        select(Location, _location_display_name(), img_count)
        .join(ImageModel, ImageModel.location_id == Location.id)
        .where(ImageModel.device == device, Location.stop == True)
        .where(or_(
            Location.name.ilike(pattern),
            Location.suburb.ilike(pattern),
            Location.city.ilike(pattern),
            Location.address.ilike(pattern),
        ))
        .group_by(Location.id)
        .order_by(desc(img_count))
        .limit(limit)
    )

    return _locations_to_info(session.execute(stmt).fetchall())

@router.post("/get-moving-periods")
def get_moving_periods(
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
        .where(Location.stop == False)
    )
    if country_filter:
        stmt = stmt.where(Location.country.in_(country_filter))

    stmt = (stmt
        .group_by(Location.id)
        .order_by(desc(func.count(ImageModel.id)))
        .limit(20)
    )

    res = session.execute(stmt).fetchall()

    locations = []
    for loc, display_name in res:
        loc_info = LocationInfo.model_validate(loc.__dict__)
        loc_info.name = display_name
        locations.append(loc_info)

    return locations


@router.post("/locations/map-markers")
async def get_map_markers(query: ValuesRequest,
                          device: str,
                          db: Session = Depends(get_session)):
    stmt = (
        select(
            Location.id,
            Location.latitude,
            Location.longitude,
            Location.name,
            Location.address,
            func.count(ImageModel.id).label("image_count")
        )
        .join(Location.images)
        .where(Location.stop == True, ImageModel.device == device, ImageModel.deleted == False)
    )

    extra_params = query.extra_params
    country_filter = extra_params.get("country")
    if country_filter:
        stmt = stmt.where(Location.country.in_(country_filter))

    bounds = extra_params.get("bounds")
    if bounds and len(bounds) == 4:
        stmt = stmt.where(
            Location.latitude.between(bounds[0], bounds[2]),
            Location.longitude.between(bounds[1], bounds[3])
        )

    stmt = stmt.group_by(Location.id)
    result = db.execute(stmt).all()

    return [
        {
            "id": str(r.id),
            "lat": r.latitude if not np.isnan(r.latitude) else None,
            "lng": r.longitude if not np.isnan(r.longitude) else None,
            "name": r.name if r.name not in ["---", "Unknown Place"] else r.address,
            "weight": r.image_count
        } for r in result
    ]


@router.post("/available-values")
def available_values(
    device: str,
    request: ValuesRequest,
    access_level: Annotated[AccessLevel, Depends(auth_dependency)] = AccessLevel.NONE,
    session: Session = Depends(get_session),
):
    _require_owner(access_level)
    field = request.field
    extra_params = request.extra_params
    logger.debug("available-values field=%s device=%s extra=%s", field, device, extra_params)
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
                .order_by(desc(func.count(ImageModel.id)))
                .limit(20)
            )
        case "country":
            stmt = (
                select(Location.country)
                .join(ImageModel, ImageModel.location_id == Location.id)
                .where(ImageModel.device == device)
                .group_by(Location.country)
                .order_by(desc(func.count(ImageModel.id)))
                .where(Location.country != None, Location.country != "")
                .where(Location.stop == True)
                .limit(20)
            )
        case "moving-cross-country":
            stmt = (
                select(Location.country)
                .join(ImageModel, ImageModel.location_id == Location.id)
                .where(ImageModel.device == device)
                .group_by(Location.country)
                .order_by(desc(func.count(ImageModel.id)))
                .where(Location.country != None, Location.country != "")
                .where(Location.stop == False)
                .limit(20)
            )
        case "year":
            stmt = select(ImageModel.year).where(ImageModel.device == device).distinct()

        case "date":
            stmt = (
                select(func.to_char(ImageModel.local_timestamp, 'YYYY-MM-DD'))
                .where(ImageModel.device == device, ImageModel.deleted == False)
                .distinct()
                .order_by(func.to_char(ImageModel.local_timestamp, 'YYYY-MM-DD'))
            )

        case _:
            raise HTTPException(status_code=400, detail="Invalid field name.")
    results = session.execute(stmt).fetchall()
    return [r[0] for r in results]

@router.get("/all-faces")
def get_all_faces(
    device: str,
    access_level: Annotated[AccessLevel, Depends(auth_dependency)] = AccessLevel.NONE,
    session: Session = Depends(get_session),
):
    _require_owner(access_level)

    cached = _FACES_CACHE.get(device)
    if cached and (time.time() - cached[0]) < _FACES_TTL:
        logger.debug("all-faces cache hit for device %s", device)
        return cached[1]

    device_row = session.execute(select(Device).where(Device.device_id == device)).scalar()
    if device_row and device_row.keep_face_recognition:
        # Whitelist mode: only show clusters that are explicitly linked to a whitelist entry
        stmt = select(PeopleCluster).where(
            PeopleCluster.device == device,
            PeopleCluster.whitelist_entry_id.isnot(None),
        )
    else:
        stmt = select(PeopleCluster).where(
            or_(
                PeopleCluster.device == device,
                PeopleCluster.people.any(ImagePerson.image.has(ImageModel.device == device)),
            )
        )
    clusters = session.execute(stmt).scalars().all()
    logger.info("Building all-faces for device %s: %d clusters", device, len(clusters))

    faces = []
    for cluster in clusters:
        face = {
            "id": str(cluster.id),
            "name": cluster.cluster_label,
            "images": []
        }
        centroid = cluster.center_embedding
        stmt = (
            select(ImagePerson.rel_bbox, ImageModel.thumbnail,
            ImagePerson.embedding.cosine_distance(centroid).label("distance"))
            .join(ImagePerson, ImagePerson.image_id == ImageModel.id)
            .where(ImageModel.device == device)
            .where(ImagePerson.cluster_id == cluster.id)
            .where(ImageModel.deleted == False)
            .where(ImageModel.thumbnail != None)
            .order_by("distance")
            .limit(4)
        )

        images = session.execute(stmt).fetchall()
        for rel_bbox, thumbnail_path, _ in images:
            image_full_path = os.path.join(THUMBNAIL_DIR, device, thumbnail_path)
            if os.path.exists(image_full_path):
                img = Image.open(image_full_path)
                bbox = to_absolute_bbox(rel_bbox, img.width, img.height)
                cropped_img = img.crop(bbox)
                buf = io.BytesIO()
                try:
                    cropped_img.save(buf, format="JPEG")
                    face["images"].append(f"data:image/jpeg;base64,{base64.b64encode(buf.getvalue()).decode()}")
                except ValueError as e:
                    logger.warning("Skipping crop for %s: %s", image_full_path, e)
        if face["images"]:
            faces.append(face)

    _FACES_CACHE[device] = (time.time(), faces)
    return faces

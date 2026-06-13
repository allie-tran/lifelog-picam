import os
import re
from typing import Annotated, List, Optional
import numpy as np
from PIL import UnidentifiedImageError
from fastapi import Depends, APIRouter, File, Form, HTTPException, UploadFile
from sqlalchemy import case, select
from sqlalchemy.orm import Session

from schemas.search import SearchQuery
from auth.auth_models import auth_dependency
from auth.types import AccessLevel
from auth.ortho import apply_transformation, get_matrix
from core.config import DIR
from database import get_session
from database.models import Image as ImageModel, Location
from auth import _require_owner
from services.embedding import get_similar_images, retrieve_image_with_filters, search_model, search_table, relationship
from core.dependencies import CamelCaseModel
from services.utils import make_video_thumbnail
from query_parse.time import (
    time_tagger,
    get_day_month,
    holiday_text_to_datetime,
    seasons as season_to_months,
    months as month_list,
)
import logging

router = APIRouter()
logger = logging.getLogger("__name__")

WORD_TO_TIMEOFDAY = {
    "morning": "morning", "afternoon": "afternoon", "midday": "midday",
    "evening": "evening", "night": "night",
    "dawn": "morning", "sunrise": "morning", "daybreak": "morning", "breakfast": "morning",
    "nightfall": "evening", "dusk": "evening", "dinner": "evening", "dinnertime": "evening",
    "sunset": "evening", "twilight": "evening",
    "lunchtime": "midday", "lunch": "midday", "noon": "midday",
    "nighttime": "night", "midnight": "night", "bedtime": "night",
    "supper": "afternoon", "suppertime": "afternoon", "teatime": "afternoon",
    "midafternoon": "afternoon",
}

MONTH_NAMES = [
    "January", "February", "March", "April", "May", "June",
    "July", "August", "September", "October", "November", "December",
]


class ParsedDateRange(CamelCaseModel):
    start: str
    end: str


MOVING_KEYWORDS = {
    "traveling", "travelling", "commuting", "driving", "on a trip",
    "on the road", "journey", "transit", "on the move",
}

class ParsedFilters(CamelCaseModel):
    time_of_days: List[str] = []
    day_of_weeks: List[str] = []
    months: List[str] = []
    years: List[int] = []
    custom_ranges: List[ParsedDateRange] = []
    countries: List[str] = []
    location_ids: List[str] = []
    is_moving: bool = False


@router.get("/parse-query")
def parse_query_endpoint(
    text: str,
    device: Optional[str] = None,
    access_level: Annotated[AccessLevel, Depends(auth_dependency)] = AccessLevel.NONE,
    session: Session = Depends(get_session),
) -> ParsedFilters:
    _require_owner(access_level)
    tags = time_tagger.tag(text.strip().lower())
    print(f"Tags for '{text}': {tags}")

    time_of_days: set[str] = set()
    day_of_weeks: set[str] = set()
    date_tuples: list[tuple] = []

    for word, tag in tags:
        if tag == "TIMEOFDAY":
            tod = WORD_TO_TIMEOFDAY.get(word.lower())
            if tod:
                time_of_days.add(tod)
        elif tag == "WEEKDAY":
            day_of_weeks.add(word.capitalize())
        elif tag in ("DATE", "HOLIDAY"):
            y, m, d = get_day_month(word) if tag == "DATE" else holiday_text_to_datetime(word)
            if any([y, m, d]):
                date_tuples.append((y, m, d))
        elif tag == "SEASON":
            for month_name in season_to_months.get(word, []):
                m_idx = month_list.index(month_name) + 1
                date_tuples.append((None, m_idx, None))

    months_set: set[str] = set()
    years_set: set[int] = set()
    custom_ranges: list[ParsedDateRange] = []

    for y, m, d in date_tuples:
        if y and m and d:
            date_str = f"{y:04d}-{m:02d}-{d:02d}"
            custom_ranges.append(ParsedDateRange(start=date_str, end=date_str))
        elif y and m:
            months_set.add(MONTH_NAMES[m - 1])
            years_set.add(y)
        elif y:
            years_set.add(y)
        elif m:
            months_set.add(MONTH_NAMES[m - 1])

    text_lower = text.strip().lower()

    is_moving = any(kw in text_lower for kw in MOVING_KEYWORDS)

    matched_countries: List[str] = []
    matched_location_ids: List[str] = []

    if device:
        display_name = case(
            (Location.name.in_(["---", "Unknown Place", ""]), Location.address),
            else_=Location.name,
        ).label("display_name")

        db_countries = session.execute(
            select(Location.country)
            .join(ImageModel, ImageModel.location_id == Location.id)
            .where(ImageModel.device == device, Location.country.isnot(None), Location.country != "")
            .distinct()
        ).scalars().all()

        matched_countries = [
            c for c in db_countries
            if re.search(r'\b' + re.escape(c.lower()) + r'\b', text_lower)
        ]

        db_locations = session.execute(
            select(Location.id, display_name)
            .join(ImageModel, ImageModel.location_id == Location.id)
            .where(ImageModel.device == device)
            .distinct()
        ).fetchall()

        matched_location_ids = [
            str(loc_id) for loc_id, name in db_locations
            if name and len(name) >= 3
            and re.search(r'\b' + re.escape(name.lower()) + r'\b', text_lower)
        ]

    return ParsedFilters(
        time_of_days=list(time_of_days),
        day_of_weeks=list(day_of_weeks),
        months=sorted(months_set, key=lambda x: MONTH_NAMES.index(x)),
        years=sorted(years_set),
        custom_ranges=custom_ranges,
        countries=matched_countries,
        location_ids=matched_location_ids,
        is_moving=is_moving,
    )

@router.get("/health")
def health_check():
    return {"status": "ok"}

@router.post("/search-images")
async def search(
    device: str,
    query: str = Form(...),
    image_paths: List[str] = Form(default=[]),
    files: List[UploadFile] = File(default=[]),
    sort_by: str = "relevance",
    access_level: Annotated[AccessLevel, Depends(auth_dependency)] = AccessLevel.NONE,
    session: Session = Depends(get_session),
):
    _require_owner(access_level)

    request = SearchQuery.model_validate_json(query)
    matrix = get_matrix(session, device)
    all_embs: List[np.ndarray] = []

    for image_path in image_paths:
        stored = session.execute(
            select(search_table.embedding)
            .join(relationship)
            .where(ImageModel.device == device)
            .where(ImageModel.image_path == image_path)
        ).scalar_one_or_none()
        if stored is not None:
            all_embs.append(np.array(stored, dtype=np.float32).flatten())

    for file in files:
        temp_path = f"{DIR}/{device}/temp_{file.filename}"
        with open(temp_path, "wb") as f_:
            f_.write(await file.read())
        try:
            img_path = temp_path
            if temp_path.endswith(".mp4") or temp_path.endswith(".h264"):
                new_path = make_video_thumbnail(temp_path)
                if new_path:
                    img_path = new_path
            raw = search_model.encode_image(img_path)
            raw = raw / np.linalg.norm(raw)
            all_embs.append(apply_transformation(raw.flatten(), matrix))
        except UnidentifiedImageError:
            pass
        finally:
            os.remove(temp_path)

    image_emb = None
    if all_embs:
        averaged = np.mean(all_embs, axis=0)
        norm = np.linalg.norm(averaged)
        image_emb = averaged / norm if norm > 0 else averaged

    if request.empty and image_emb is None:
        return []

    segments, summary = retrieve_image_with_filters(
        session,
        device,
        request,
        sort_by,
        k=1000,
        image_emb=image_emb,
    )
    return {"segments": segments, **summary}


@router.get("/similar-images")
def similar_images(
    image: str,
    device: str,
    access_level: Annotated[AccessLevel, Depends(auth_dependency)] = AccessLevel.NONE,
    session: Session = Depends(get_session),
):
    _require_owner(access_level)

    return get_similar_images(
        session,
        device,
        image,
        k=1000,
    )


@router.post("/similar-images")
def similar_images_by_upload(
    file: UploadFile,
    device: str,
    access_level: Annotated[AccessLevel, Depends(auth_dependency)] = AccessLevel.NONE,
    session: Session = Depends(get_session),
):
    _require_owner(access_level)

    temp_path = f"{DIR}/{device}/temp_{file.filename}"

    with open(temp_path, "wb") as f:
        f.write(file.file.read())
    try:
        results = get_similar_images(
            session,
            device,
            temp_path,
            k=1000,
        )

    except UnidentifiedImageError:
        raise HTTPException(status_code=400, detail="Invalid image file.")
    finally:
        os.remove(temp_path)

    return results


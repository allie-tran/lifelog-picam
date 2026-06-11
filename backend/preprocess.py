import os
from typing import List

import numpy as np
import uuid
from sqlalchemy import and_, case, extract, func, or_, select, text

from app_types import (
    AppFeatures,
    CustomFastAPI,
    LifelogImage,
)
from app_types.search import ResultSummary, SearchQuery
from auth.ortho import apply_transformation, get_matrix
from constants import DIR, THUMBNAIL_DIR
from database.models import Image, ImageEmbedding, ImageGPS, ImagePerson, Location, PeopleCluster
from visual import clip_model
from scripts.utils import make_video_thumbnail
from query_parse.extract_info import Query
from database.types import _orm_to_lifelog
from collections import Counter


os.makedirs(THUMBNAIL_DIR, exist_ok=True)

def load_features(app: CustomFastAPI) -> AppFeatures:
    app_features = AppFeatures()
    app.features = app_features
    return app_features


search_model = clip_model
search_table = ImageEmbedding
relationship = Image.embedding

time_of_days_to_hours = {
    "morning": (5, 12),
    "afternoon": (12, 17),
    "evening": (17, 21),
    "night": (21, 5),
    "midday": (11, 13)
}

def create_stmt_with_embedding(emb, device_id):
    stmt = (
        select(
            search_table.embedding.cosine_distance(emb).label("distance"),
            search_table.image_id,
            Image,
        )
        .where(
            Image.deleted == False,
            Image.device == device_id
        )
        .order_by("distance")
        .join(relationship)
    )
    return stmt

def create_stmt_generic(device_id):
    stmt = (
        select(Image)
        .where(
            Image.deleted == False,
            Image.device == device_id
        )
    )
    return stmt

def retrieve_image_with_filters(session, device_id: str, query: SearchQuery, sort_by, k, image_emb: np.ndarray | None = None):
    # Do auto_filters later TODO!!
    text_emb = None
    if query.text:
        text_emb = search_model.encode_text(query.text)
        matrix = get_matrix(session, device_id)
        text_emb = apply_transformation(text_emb, matrix)

    if text_emb is not None and image_emb is not None:
        combined = text_emb + image_emb
        norm = np.linalg.norm(combined)
        emb = combined / norm if norm > 0 else combined
        stmt = create_stmt_with_embedding(emb, device_id)
    elif text_emb is not None:
        stmt = create_stmt_with_embedding(text_emb, device_id)
    elif image_emb is not None:
        stmt = create_stmt_with_embedding(image_emb, device_id)
    else:
        stmt = create_stmt_generic(device_id)

    # Time/day filters — row/col selectors and individual cell selectors are OR'd together
    _DOW = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]
    _MONTHS = ["January", "February", "March", "April", "May", "June",
               "July", "August", "September", "October", "November", "December"]

    def _hour_cond(tod: str):
        start_hour, end_hour = time_of_days_to_hours[tod]
        if start_hour < end_hour:
            return and_(Image.hour >= start_hour, Image.hour < end_hour)
        return or_(Image.hour >= start_hour, Image.hour < end_hour)

    temporal_conds = []

    # Row/col based: (time_of_days OR …) AND (day_of_weeks OR …)
    if query.time_of_days or query.day_of_weeks:
        row_conds = []
        if query.time_of_days:
            row_conds.append(or_(*[_hour_cond(t) for t in query.time_of_days]))
        if query.day_of_weeks:
            day_nums = [_DOW.index(d) + 1 for d in query.day_of_weeks]
            row_conds.append(extract("dow", Image.local_timestamp).in_(day_nums))
        temporal_conds.append(and_(*row_conds))

    # Individual (time, day-of-week) cells
    for cell in query.time_day_cells:
        temporal_conds.append(and_(
            _hour_cond(cell.time_of_day),
            extract("dow", Image.local_timestamp) == (_DOW.index(cell.day_of_week) + 1),
        ))

    # Individual (time, month) cells
    for cell in query.time_month_cells:
        temporal_conds.append(and_(
            _hour_cond(cell.time_of_day),
            Image.month == (_MONTHS.index(cell.month) + 1),
        ))

    if temporal_conds:
        stmt = stmt.where(or_(*temporal_conds))

    if query.seasons:
        season_months = {
            "spring": [3, 4, 5],
            "summer": [6, 7, 8],
            "autumn": [9, 10, 11],
            "winter": [12, 1, 2]
        }
        season_conditions = []
        for season in query.seasons:
            months = season_months[season]
            season_conditions.append(Image.month.in_(months))
        stmt = stmt.where(or_(*season_conditions))

    if query.months:
        month_num = [["January", "February", "March", "April", "May", "June", "July", "August", "September", "October", "November", "December"].index(month) + 1 for month in query.months]
        stmt = stmt.where(or_(*[Image.month.in_(month_num)]))

    if query.years:
        stmt = stmt.where(or_(*[Image.year.in_(query.years)]))

    if query.custom_ranges:
        range_conditions = []
        for tr in query.custom_ranges:
            if tr.start and tr.end and tr.start.date() == tr.end.date():
                # Single day: use pre-extracted columns to avoid timezone issues
                range_conditions.append(
                    and_(Image.year == tr.start.year, Image.month == tr.start.month, Image.day == tr.start.day)
                )
            elif tr.start and tr.end:
                range_conditions.append(
                    and_(Image.local_timestamp >= tr.start, Image.local_timestamp < tr.end)
                )
            elif tr.start:
                range_conditions.append(Image.local_timestamp >= tr.start)
            elif tr.end:
                range_conditions.append(Image.local_timestamp < tr.end)
        if range_conditions:
            stmt = stmt.where(or_(*range_conditions))

    # Location filters
    if query.is_moving or query.countries or query.location_ids:
        # merge with location table
        stmt = stmt.join(Image.location)
        if query.is_moving:
            stmt = stmt.where(Location.stop == False)
        if query.countries:
            stmt = stmt.where(Location.country.in_(query.countries))
        if query.location_ids:
            # convert to UUID
            location_ids = [uuid.UUID(loc_id) for loc_id in query.location_ids]
            stmt = stmt.where(Location.id.in_(location_ids))

    if query.bounds:
        stmt = stmt.join(Image.gps)
        min_lat, min_lon, max_lat, max_lon = query.bounds
        stmt = stmt.where(
            ImageGPS.latitude.between(min_lat, max_lat),
            ImageGPS.longitude.between(min_lon, max_lon)
        )

    # People
    if query.people_ids:
        people_ids = [uuid.UUID(pid) for pid in query.people_ids]
        stmt = stmt.join(Image.people).where(Image.people.any(ImagePerson.cluster_id.in_(people_ids)))

    # Execute the query
    stmt = stmt.limit(k)
    session.execute(text(f"SET hnsw.ef_search = {max(k, 200)}"))
    session.execute(text(f"SET hnsw.iterative_scan = strict_order"))
    rows = session.execute(stmt).fetchall()
    print(f"Found {len(rows)} results for device {device_id} with sort_by {sort_by}")

    records = [_orm_to_lifelog(row.Image) for row in rows]

    # group by segment id
    segments: dict[str, List[LifelogImage]] = {}
    for record in records:
        segment_key = f"{record.date}_{record.segment_id}"
        if segment_key in segments:
            segments[segment_key].append(record)
        else:
            segments[segment_key] = [record]

    # Build summary data
    image_paths = [r.image_path for r in records]
    top_locations: list[dict] = []
    top_countries: list[dict] = []
    top_people: list[dict] = []

    if image_paths:
        display_name_expr = case(
            (Location.name.in_(["---", "Unknown Place", ""]), Location.address),
            else_=Location.name,
        ).label("display_name")

        location_rows = session.execute(
            select(
                Location.id,
                Location.name,
                Location.address,
                Location.country,
                Location.info,
                Location.latitude,
                Location.longitude,
                func.count().label("cnt"),
            )
            .join(Image, Image.location_id == Location.id)
            .where(Image.image_path.in_(image_paths), Image.device == device_id)
            .group_by(Location.id)
            .order_by(func.count().desc())
            .limit(5)
        ).fetchall()
        top_locations = [
            {
                "id": str(row.id) if row.id else None,
                "name": (
                    row.name
                    if row.name and row.name not in ("---", "Unknown Place", "")
                    else (row.address or "Unknown")
                ),
                "address": row.address,
                "country": row.country or "",
                "info": row.info,
                "latitude": row.latitude if row.latitude and not (row.latitude != row.latitude) else None,
                "longitude": row.longitude if row.longitude and not (row.longitude != row.longitude) else None,
                "count": row.cnt,
            }
            for row in location_rows
        ]

        country_rows = session.execute(
            select(Location.country, func.count().label("cnt"))
            .join(Image, Image.location_id == Location.id)
            .where(
                Image.image_path.in_(image_paths),
                Image.device == device_id,
                Location.country.isnot(None),
                Location.country != "",
            )
            .group_by(Location.country)
            .order_by(func.count().desc())
            .limit(5)
        ).fetchall()
        top_countries = [{"name": row.country, "count": row.cnt} for row in country_rows]

        people_rows = session.execute(
            select(PeopleCluster.cluster_label, func.count().label("cnt"))
            .join(ImagePerson, ImagePerson.cluster_id == PeopleCluster.id)
            .join(Image, Image.id == ImagePerson.image_id)
            .where(Image.image_path.in_(image_paths), Image.device == device_id)
            .group_by(PeopleCluster.cluster_label)
            .order_by(func.count().desc())
            .limit(5)
        ).fetchall()
        top_people = [{"name": row.cluster_label, "count": row.cnt} for row in people_rows]

    summary = {
        "topLocations": top_locations,
        "topCountries": top_countries,
        "topPeople": top_people,
    }
    return list(segments.values()), summary

time_of_days = {
    "morning": (5, 12),
    "afternoon": (12, 17),
    "evening": (17, 21),
    "night": (21, 5),
    "midday": (11, 13)
}

def create_result_summary(records: List[LifelogImage]) -> ResultSummary:
    summary = ResultSummary(
        total_images=len(records)
    )

    # time breakdowns
    time_of_day_counts = Counter()
    for record in records:
        hour = record.timestamp.hour
        for time_of_day, (start, end) in time_of_days.items():
            if start < end:
                if start <= hour < end:
                    time_of_day_counts[time_of_day] += 1
            else:
                if hour >= start or hour < end:
                    time_of_day_counts[time_of_day] += 1
    summary.time_of_days = list(time_of_day_counts.items())

    # location breakdowns
    # TODO!

    return summary

def search_by_filters(session, device_id, filters, sort_by, k):
    stmt = (
        select(Image)
        .where(
            Image.deleted == False,
            Image.device == device_id
        )
    )

    for sql_filter in filters:
        print(f"Applying filter: {sql_filter}")
        if sql_filter is not None:
            stmt = sql_filter(stmt)

    if sort_by == "time":
        stmt = stmt.order_by(Image.timestamp.desc())
    else:
        stmt = stmt.order_by(Image.id.desc())  # Default sorting

    stmt = stmt.limit(k)
    rows = session.execute(stmt).fetchall()
    print(f"Found {len(rows)} results for device {device_id} with sort_by {sort_by}")

    records = [_orm_to_lifelog(row.Image) for row in rows]
    return records


def search_by_embedding(session, emb, device_id, k, sort_by, filters=[]):
    stmt = create_stmt_with_embedding(emb, device_id)
    for sql_filter in filters:
        print(f"Applying filter: {sql_filter}")
        if sql_filter is not None:
            stmt = sql_filter(stmt)

    stmt = stmt.limit(k)
    # print(stmt.compile(compile_kwargs={"literal_binds": True}))
    session.execute(text(f"SET hnsw.ef_search = {max(k, 200)}"))
    session.execute(text(f"SET hnsw.iterative_scan = strict_order"))
    rows = session.execute(stmt).fetchall()
    print(f"Found {len(rows)} results for device {device_id} with sort_by {sort_by}")
    sort_by_timestamp = sort_by == "time"
    if sort_by_timestamp:
        rows = sorted(rows, key=lambda row: row.Image.timestamp, reverse=True)

    records = [_orm_to_lifelog(row.Image) for row in rows]
    return records


def get_similar_images(
    session,
    device_id: str,
    image: str,
    k,
):
    if "temp" in image:
        try:
            path = image
            if path.endswith(".mp4") or path.endswith(".h264"):
                # use video thumbnail
                new_path = make_video_thumbnail(f"{DIR}/{device_id}/{image}")
                if new_path:
                    path = new_path

            emb = search_model.encode_image(path)
            emb = emb / np.linalg.norm(emb)
            emb = emb.flatten()
            emb = apply_transformation(emb, get_matrix(session, device_id))
        except Exception as e:
            print(f"Error encoding image {image}: {e}")
            results: List[LifelogImage] = []
            return results
    else:
        emb = session.execute(
            select(search_table.embedding)
            .join(relationship)
            .where(Image.device == device_id)
            .where(Image.image_path == image)
        ).scalar_one_or_none()
        emb = np.frombuffer(emb, dtype=np.float32) if emb is not None else None

    return search_by_embedding(session, emb, device_id, k, sort_by="relevance")

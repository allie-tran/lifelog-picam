import os
from typing import List

import numpy as np
import uuid
from sqlalchemy import and_, extract, func, or_, select, text

from app_types import (
    AppFeatures,
    CustomFastAPI,
    LifelogImage,
)
from app_types.search import ResultSummary, SearchQuery
from auth.ortho import apply_transformation, get_matrix
from constants import DIR, THUMBNAIL_DIR
from database.models import Image, ImageEmbedding, ImagePerson, Location
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

def retrieve_image_with_filters(session, device_id: str, query: SearchQuery, sort_by, k):
    # Do auto_filters later TODO!!
    if query.text:
        emb = search_model.encode_text(query.text)
        stmt = create_stmt_with_embedding(emb, device_id)
    else:
        stmt = create_stmt_generic(device_id)

    # Time filters
    if query.time_of_days:
        time_conditions = []
        for time in query.time_of_days:
            start_hour, end_hour = time_of_days_to_hours[time]

            if start_hour < end_hour:
                # Standard range (e.g., 9 to 17)
                time_conditions.append(
                    and_(Image.hour >= start_hour, Image.hour < end_hour)
                )
            else:
                # Wrap-around range (e.g., 22 to 04)
                # This logic says: Hour is >= 22 OR Hour is < 04
                time_conditions.append(
                    or_(Image.hour >= start_hour, Image.hour < end_hour)
                )
        # Apply all gathered time ranges as a single OR block
        stmt = stmt.where(or_(*time_conditions))


    if query.day_of_weeks:
        day_nums = [["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"].index(day) + 1 for day in query.day_of_weeks]
        stmt = stmt.where(or_(*[extract("dow", Image.local_timestamp).in_(day_nums)]))

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
            Image.gps.latitude.between(min_lat, max_lat),
            Image.gps.longitude.between(min_lon, max_lon)
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

    return list(segments.values())

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

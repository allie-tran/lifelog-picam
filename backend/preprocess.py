import os
from typing import List

import numpy as np
from sqlalchemy import and_, select


from app_types import (
    AppFeatures,
    CustomFastAPI,
    LifelogImage,
)
from auth.ortho import apply_transformation, get_matrix
from constants import DIR, THUMBNAIL_DIR
from database.models import Image, ImageEmbedding
from database.types import ImageRecord
from scripts.utils import make_video_thumbnail
from visual import clip_model
from query_parse.extract_info import Query
from database.types import _orm_to_lifelog


os.makedirs(THUMBNAIL_DIR, exist_ok=True)


def load_features(app: CustomFastAPI) -> AppFeatures:
    app_features = AppFeatures()
    # for device in os.listdir(feature_dir):
    #     device_features = DeviceFeatures()
    #     app_features[device] = device_features

    #     app_features[device]["conclip"] = CLIPFeatures(
    #         collection=open_collection(device, "conclip")
    #     )
    #     app_features[device]["faces"] = CLIPFeatures(
    #         collection=open_face_collection(device)
    #     )

    app.features = app_features
    return app_features



def retrieve_image(session, device_id: str, text: str, sort_by, k):
    query = Query(text)
    filters = query.time_to_filters()

    emb = clip_model.encode_text(text)
    emb = apply_transformation(emb, get_matrix(session, device_id))

    records = search_by_embedding(session, emb, device_id, k, sort_by, filters=filters)

    # group by segment id
    segments: dict[str, List[LifelogImage]] = {}
    for record in records:
        segment_key = f"{record.date}_{record.segment_id}"
        if segment_key in segments:
            segments[segment_key].append(record)
        else:
            segments[segment_key] = [record]

    return list(segments.values())


def search_by_embedding(session, emb, device_id, k, sort_by, filters=[]):
    stmt = (
        select(
            ImageEmbedding.embedding.cosine_distance(emb).label("distance"),
            ImageEmbedding.image_id,
            Image,
        )
        .where(
            and_(
                ImageEmbedding.embedding.isnot(None),
                Image.deleted == False,
                Image.device == device_id,
            )
        )
        .order_by("distance")
        .join(Image, Image.id == ImageEmbedding.image_id)
    )

    for sql_filter in filters:
        print(f"Applying filter: {sql_filter}")
        if sql_filter is not None:
            stmt = sql_filter(stmt)

    stmt = stmt.limit(k)
    print(f"Executing SQL: {stmt}")

    rows = session.execute(stmt).fetchall()

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
        # query_vector, *_ = encode_image(device_id, image, np.empty((0, DIM)), [])
        try:
            path = image
            if path.endswith(".mp4") or path.endswith(".h264"):
                # use video thumbnail
                new_path = make_video_thumbnail(f"{DIR}/{device_id}/{image}")
                if new_path:
                    path = new_path

            emb = clip_model.encode_image(path)
            emb = emb / np.linalg.norm(emb)
            emb = emb.flatten()
            emb = apply_transformation(emb, get_matrix(session, device_id))
        except Exception as e:
            print(f"Error encoding image {image}: {e}")
            results: List[LifelogImage] = []
            return results
    else:
        emb = session.execute(
            select(ImageEmbedding.embedding)
            .join(Image, Image.id == ImageEmbedding.image_id)
            .where(Image.device == device_id)
            .where(Image.image_path == image)
        ).scalar_one_or_none()
        print(emb)
        emb = np.frombuffer(emb, dtype=np.float32) if emb is not None else None

    return search_by_embedding(session, emb, device_id, k, sort_by="relevance")

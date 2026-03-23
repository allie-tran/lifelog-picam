"""
types.py — Drop-in replacement for the MongoDB ODM types.

LifelogImage stays exactly as-is (Pydantic schema, used everywhere).
ImageRecord now talks to PostgreSQL via SQLAlchemy instead of MongoDB ODM.

Migration notes for call sites:
    - ImageRecord.find({"deleted": False})
        → ImageRecord.find(session, deleted=False)

    - ImageRecord.find({"image_path": path})
        → ImageRecord.find_one(session, image_path=path)

    - ImageRecord.find({}, sort=[("timestamp", -1)], limit=100)
        → ImageRecord.find(session, sort="timestamp", sort_desc=True, limit=100)

    - ImageRecord.find({"segment_id": sid}, distinct="image_path")
        → ImageRecord.distinct(session, "image_path", segment_id=sid)
"""

from __future__ import annotations

from typing import (
    Any,
    Dict,
    Iterator,
    Optional,
    Sequence,
    Tuple,
    Mapping,
    Union,
    TypeVar,
)
from sqlalchemy import (
    select,
    asc,
    desc,
    func,
    distinct as sa_distinct,
    delete,
    insert as sa_insert,
)
from sqlalchemy.orm import Session
from mongodb_odm import Document

from app_types import DaySummary, LifelogImage
from database.models import Image, ImagePerson, ImageOCR, ImageGPS


DICT_TYPE = Dict[str, Any]
SORT_TYPE = Union[str, Sequence[Tuple[str, Union[int, str, Mapping[str, Any]]]]]
DocumentType = TypeVar("DocumentType", bound=Mapping[str, Any])


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _orm_to_lifelog(row: Image) -> LifelogImage:
    """Convert a SQLAlchemy Image row → LifelogImage Pydantic model."""
    from app_types import GPSInfo, ObjectDetection, ProcessedInfo

    gps = None
    if row.gps:
        gps = GPSInfo(
            timestamp=row.gps.timestamp or 0.0,
            latitude=row.gps.latitude,
            longitude=row.gps.longitude,
            elevation=row.gps.elevation,
        )

    people = [
        ObjectDetection(
            label=p.label or "",
            confidence=p.confidence or 0.0,
            bbox=p.bbox or [],
            embedding=list(p.embedding) if p.embedding is not None else None,
            cluster_label=p.cluster_label,
        )
        for p in (row.people or [])
    ]

    objects = [
        ObjectDetection(
            label=o.label or "",
            confidence=o.confidence or 0.0,
            bbox=o.bbox or [],
            embedding=list(o.embedding) if o.embedding is not None else None,
            cluster_label=o.cluster_label,
        )
        for o in (row.objects or [])
    ]

    processed = ProcessedInfo(
        yolo=row.proc_yolo or False,
        face_recognition=row.proc_face_recognition or False,
        encoded=row.proc_encoded or False,
        sam3=row.proc_sam3 or False,
    )

    return LifelogImage(
        device=row.device or "",
        image_path=row.image_path,
        timestamp=row.timestamp.timestamp() if row.timestamp else 0.0,
        seconds_from_midnight=row.seconds_from_midnight or 0,
        thumbnail=row.thumbnail,
        is_video=row.is_video,
        objects=objects,
        people=people,
        deleted=row.deleted or False,
        delete_time=row.delete_time,
        date=row.date or "",
        hour=row.hour or "",
        segment_id=row.segment_id,
        activity=row.activity or "",
        activity_description=row.activity_description or "",
        activity_confidence=row.activity_confidence or "",
        gps=gps,
        processed=processed,
        new=row.new or False,
    )


def _apply_kwargs_filters(stmt, model, kwargs: dict):
    """Apply arbitrary column=value filters from kwargs."""
    for key, val in kwargs.items():
        col = getattr(model, key, None)
        if col is None:
            raise ValueError(f"Unknown filter column on {model.__tablename__}: '{key}'")
        stmt = stmt.where(col == val)
    return stmt


# ---------------------------------------------------------------------------
# ImageRecord — drop-in replacement for the MongoDB Document subclass
# ---------------------------------------------------------------------------


class ImageRecord:
    """
    PostgreSQL replacement for the MongoDB ImageRecord(Document, LifelogImage).

    All methods return LifelogImage instances to preserve compatibility
    with existing call sites.

    FastAPI usage:
        @router.get("/images", response_model=list[LifelogImage])
        def list_images(session=Depends(get_session)):
            return ImageRecord.find(session, deleted=False, limit=50)

        @router.get("/images/{image_path:path}", response_model=LifelogImage)
        def get_image(image_path: str, session=Depends(get_session)):
            img = ImageRecord.find_one(session, image_path=image_path)
            if not img:
                raise HTTPException(404)
            return img
    """

    @classmethod
    def model_validate(cls, row: Image) -> LifelogImage:
        """Convert a SQLAlchemy Image ORM row → LifelogImage Pydantic model."""
        return _orm_to_lifelog(row)

    @staticmethod
    def model_dump(image: LifelogImage, **kwargs) -> dict:
        """Serialize a LifelogImage to a dict (passes through to Pydantic)."""
        return image.model_dump(**kwargs)

    # ------------------------------------------------------------------
    # find() — mirrors the old MongoDB signature
    # ------------------------------------------------------------------

    @classmethod
    def find(
        cls,
        session: Session,
        filter: Optional[DICT_TYPE] = None,  # kept for compat — prefer kwargs
        projection: Optional[DICT_TYPE] = None,  # ignored (no MongoDB projections)
        sort: Optional[Any] = None,
        sort_desc: bool = False,  # new param for simple sort direction
        skip: Optional[int] = None,
        limit: Optional[int] = None,
        distinct: Optional[str] = None,
        **kwargs: Any,
    ) -> Iterator[LifelogImage]:
        """
        Find images, yielding LifelogImage objects.

        Old style (still works):
            ImageRecord.find(session, {"deleted": False}, sort=[("timestamp", -1)])

        New style (preferred):
            ImageRecord.find(session, deleted=False, sort="timestamp", sort_desc=True)
        """
        # Merge flat filter dict into kwargs
        if filter:
            kwargs.update(filter)

        if distinct:
            yield from cls.distinct(session, distinct, **kwargs)
            return

        stmt = select(Image)
        stmt = _apply_kwargs_filters(stmt, Image, kwargs)

        # Sort — handle both MongoDB-style [("field", -1)] and plain string
        if sort:
            if isinstance(sort, str):
                col = getattr(Image, sort, None)
                if col is not None:
                    stmt = stmt.order_by(desc(col) if sort_desc else asc(col))
            elif isinstance(sort, (list, tuple)):
                for field, direction in sort:
                    col = getattr(Image, field, None)
                    if col is not None:
                        stmt = stmt.order_by(desc(col) if direction == -1 else asc(col))

        if skip:
            stmt = stmt.offset(skip)
        if limit:
            stmt = stmt.limit(limit)

        for row in session.execute(stmt).scalars():
            yield _orm_to_lifelog(row)

    # ------------------------------------------------------------------
    # find_one() — returns a single LifelogImage or None
    # ------------------------------------------------------------------

    @classmethod
    def find_one(
        cls,
        session: Session,
        filter: Optional[DICT_TYPE] = None,
        **kwargs: Any,
    ) -> Optional[LifelogImage]:
        if filter:
            kwargs.update(filter)

        stmt = select(Image)
        stmt = _apply_kwargs_filters(stmt, Image, kwargs)

        row = session.execute(stmt.limit(1)).scalars().first()
        return _orm_to_lifelog(row) if row else None

    # ------------------------------------------------------------------
    # distinct() — mirrors cursor.distinct(field)
    # ------------------------------------------------------------------

    @classmethod
    def distinct(
        cls,
        session: Session,
        field: str,
        **kwargs: Any,
    ) -> Iterator[Any]:
        col = getattr(Image, field, None)
        if col is None:
            raise ValueError(f"Unknown column: '{field}'")

        stmt = select(sa_distinct(col))
        stmt = _apply_kwargs_filters(stmt, Image, kwargs)

        for val in session.execute(stmt).scalars():
            yield val

    # ------------------------------------------------------------------
    # count() — mirrors collection.count_documents()
    # ------------------------------------------------------------------

    @classmethod
    def count(
        cls,
        session: Session,
        filter: Optional[DICT_TYPE] = None,
        **kwargs: Any,
    ) -> int:
        if filter:
            kwargs.update(filter)

        stmt = select(func.count()).select_from(Image)
        stmt = _apply_kwargs_filters(stmt, Image, kwargs)
        return session.execute(stmt).scalar()

    # ------------------------------------------------------------------
    # delete_many() — mirrors collection.delete_many()
    # ------------------------------------------------------------------

    @classmethod
    def delete_many(
        cls,
        session: Session,
        filter: Optional[DICT_TYPE] = None,
        **kwargs: Any,
    ) -> int:
        """
        Delete images matching the filter. Returns the number of rows deleted.

        Note: This performs a hard delete. If you want to mark as deleted instead, use save() with deleted=True.
        """

        if filter:
            kwargs.update(filter)

        stmt = delete(Image)
        stmt = _apply_kwargs_filters(stmt, Image, kwargs)
        result = session.execute(stmt)
        session.commit()
        return result.rowcount

    # ------------------------------------------------------------------
    # save() — insert or update a LifelogImage
    # ------------------------------------------------------------------

    @classmethod
    def save(
        cls,
        session: Session,
        image: LifelogImage,
    ) -> Image:
        """
        Upsert a LifelogImage into the database.
        Matches on image_path (unique key).
        """
        from datetime import datetime, timezone
        from sqlalchemy.dialects.postgresql import insert as pg_insert

        ts = (
            datetime.fromtimestamp(image.timestamp, tz=timezone.utc)
            if image.timestamp
            else None
        )
        year = month = day = None
        if image.date:
            try:
                parts = image.date.split("-")
                year, month, day = int(parts[0]), int(parts[1]), int(parts[2])
            except (ValueError, IndexError):
                pass

        stmt = pg_insert(Image).values(
            image_path=image.image_path,
            thumbnail=image.thumbnail,
            is_video=image.is_video,
            device=image.device,
            timestamp=ts,
            date=image.date,
            year=year,
            month=month,
            day=day,
            seconds_from_midnight=image.seconds_from_midnight,
            segment_id=image.segment_id,
            activity=image.activity,
            activity_description=image.activity_description,
            activity_confidence=image.activity_confidence,
            deleted=image.deleted,
            delete_time=image.delete_time,
            new=image.new,
            proc_yolo=image.processed.yolo,
            proc_encoded=image.processed.encoded,
            proc_face_recognition=image.processed.face_recognition,
            proc_sam3=image.processed.sam3,
        )
        insert_stmt = stmt.on_conflict_do_update(
            index_elements=["image_path"],
            set_={
                "deleted": stmt.excluded.deleted,
                "segment_id": stmt.excluded.segment_id,
                "activity": stmt.excluded.activity,
                "activity_description": stmt.excluded.activity_description,
                "activity_confidence": stmt.excluded.activity_confidence,
                "proc_yolo": stmt.excluded.proc_yolo,
                "proc_encoded": stmt.excluded.proc_encoded,
                "proc_face_recognition": stmt.excluded.proc_face_recognition,
                "proc_sam3": stmt.excluded.proc_sam3,
                "new": stmt.excluded.new,
            },
        )
        result = session.execute(insert_stmt.returning(Image.id))
        session.flush()
        return result.scalar()

    @classmethod
    def update_many(
        cls,
        session: Session,
        filter: Optional[DICT_TYPE] = None,
        update: Optional[DICT_TYPE] = None,
        upsert: bool = False,
        **kwargs: Any,
    ) -> int:
        """
        Update multiple images matching the filter. Returns the number of rows updated.

        Note: This performs a hard update. If you want to mark as deleted instead, use save() with deleted=True.
        """
        if filter:
            kwargs.update(filter)

        stmt = pg_insert(Image).values(**update)
        if upsert:
            stmt = stmt.on_conflict_do_update(
                index_elements=["image_path"],
                set_=update,
            )
        else:
            stmt = stmt.on_conflict_do_nothing()
        result = session.execute(stmt)
        session.commit()
        return result.rowcount

    @classmethod
    def aggregate(
        cls, session: Session, pipeline: list[DICT_TYPE]
    ) -> Iterator[DICT_TYPE]:
        """
        Placeholder for MongoDB-style aggregation pipelines.
        Not implemented — would require parsing the pipeline and translating to SQL.
        """
        raise NotImplementedError(
            "Aggregate pipelines are not supported in this implementation."
        )

    # ------------------------------------------------------------------
    # Vector / face / GPS searches — new capabilities
    # ------------------------------------------------------------------

    @classmethod
    def find_segments(
        cls,
        session: Session,
        date: str,
        hour: str,
        device: str,
        deleted: bool = False,
        page: int = 0,
        page_size: int = 20,
    ) -> list[dict[str, Any]]:
        """
        Replacement for the MongoDB aggregate pipeline that groups images by segment_id.

        Returns a list of dicts:
            [
                {"segment_id": 3, "images": [LifelogImage, ...]},
                {"segment_id": 2, "images": [LifelogImage, ...]},
                ...
            ]
        sorted by segment_id descending, paginated by page/page_size.

        Old MongoDB call:
            segments = ImageRecord.aggregate([
                {"$match": {"date": date, "deleted": False, "hour": hour, "device": device}},
                {"$group": {"_id": "$segment_id", "images": {"$push": "$$ROOT"}}},
                {"$sort": {"_id": -1}},
            ])
        New call:
            segments = ImageRecord.find_segments(session, date=date, hour=hour, device=device)
        """
        # Step 1: find all matching images ordered by segment_id desc, then timestamp
        rows = (
            session.execute(
                select(Image)
                .where(Image.date == date)
                .where(Image.hour == str(hour).zfill(2))
                .where(Image.device == device)
                .where(Image.deleted == deleted)
                .order_by(desc(Image.segment_id), asc(Image.timestamp))
            )
            .scalars()
            .all()
        )

        # Step 2: group in Python (avoids complex lateral join)
        grouped: dict[Any, list[LifelogImage]] = {}
        for row in rows:
            key = row.segment_id  # None is a valid group (unsegmented images)
            if key not in grouped:
                grouped[key] = []
            grouped[key].append(_orm_to_lifelog(row))

        # Step 3: sort segment keys descending (mirrors $sort: {_id: -1})
        sorted_keys = sorted(
            grouped.keys(),
            key=lambda k: (k is None, k if k is not None else 0),
            reverse=True,
        )

        # Step 4: paginate
        paginated_keys = sorted_keys[page * page_size : (page + 1) * page_size]

        return [{"segment_id": key, "images": grouped[key]} for key in paginated_keys]

    @classmethod
    def find_similar(
        cls,
        session: Session,
        embedding: list[float],
        *,
        limit: int = 10,
        deleted: bool = False,
    ) -> Iterator[tuple[LifelogImage, float]]:
        stmt = (
            select(Image, Image.embedding.cosine_distance(embedding).label("distance"))
            .where(Image.embedding.isnot(None))
            .where(Image.deleted == deleted)
            .order_by(Image.embedding.cosine_distance(embedding))
            .limit(limit)
        )
        for row, distance in session.execute(stmt):
            yield _orm_to_lifelog(row), distance

    @classmethod
    def find_by_face(
        cls,
        session: Session,
        face_embedding: list[float],
        *,
        limit: int = 10,
        min_confidence: float = 0.5,
    ) -> Iterator[tuple[LifelogImage, float]]:
        stmt = (
            select(
                Image,
                ImagePerson.embedding.cosine_distance(face_embedding).label("distance"),
            )
            .join(ImagePerson, ImagePerson.image_id == Image.id)
            .where(ImagePerson.embedding.isnot(None))
            .where(ImagePerson.confidence >= min_confidence)
            .order_by(ImagePerson.embedding.cosine_distance(face_embedding))
            .limit(limit)
        )
        for row, distance in session.execute(stmt):
            yield _orm_to_lifelog(row), distance

    @classmethod
    def find_by_ocr(
        cls,
        session: Session,
        query: str,
        *,
        limit: int = 10,
        exact: bool = False,
    ) -> Iterator[LifelogImage]:
        if exact:
            stmt = (
                select(Image)
                .join(ImageOCR, ImageOCR.image_id == Image.id)
                .where(ImageOCR.text.ilike(f"%{query}%"))
                .order_by(ImageOCR.confidence.desc())
                .limit(limit)
            )
        else:
            ts_query = func.plainto_tsquery("english", query)
            ts_vector = func.to_tsvector("english", ImageOCR.text)
            stmt = (
                select(Image)
                .join(ImageOCR, ImageOCR.image_id == Image.id)
                .where(ts_vector.op("@@")(ts_query))
                .order_by(func.ts_rank(ts_vector, ts_query).desc())
                .limit(limit)
            )
        for row in session.execute(stmt).scalars():
            yield _orm_to_lifelog(row)

    @classmethod
    def find_near(
        cls,
        session: Session,
        lat: float,
        lon: float,
        *,
        radius_m: float = 500,
        limit: int = 10,
    ) -> Iterator[tuple[LifelogImage, float]]:
        from geoalchemy2 import Geography
        from geoalchemy2.functions import ST_DWithin, ST_Distance, ST_MakePoint

        point = func.cast(ST_MakePoint(lon, lat), Geography)
        stmt = (
            select(Image, ST_Distance(ImageGPS.geog, point).label("dist_m"))
            .join(ImageGPS, ImageGPS.image_id == Image.id)
            .where(ST_DWithin(ImageGPS.geog, point, radius_m))
            .order_by(ST_Distance(ImageGPS.geog, point))
            .limit(limit)
        )
        for row, dist_m in session.execute(stmt):
            yield _orm_to_lifelog(row), dist_m


# ---------------------------------------------------------------------------
# DaySummaryRecord — stub, implement if needed
# ---------------------------------------------------------------------------


class DaySummaryRecord:
    """PostgreSQL equivalent of DaySummaryRecord — to be implemented."""

    pass


# ---------------------------------------------------------------------------
# FastAPI session dependency
# ---------------------------------------------------------------------------
# Add this to your dependencies.py or a new db.py:
#
#   from sqlalchemy import create_engine
#   from sqlalchemy.orm import Session, sessionmaker
#
#   engine = create_engine(PG_URI)
#   SessionLocal = sessionmaker(bind=engine)
#
#   def get_session():
#       with SessionLocal() as session:
#           yield session
#
# Then in your routes:
#
#   from fastapi import Depends
#   from sqlalchemy.orm import Session
#
#   @router.get("/images", response_model=list[LifelogImage])
#   def list_images(
#       deleted: bool = False,
#       limit: int = 50,
#       session: Session = Depends(get_session),
#   ):
#       return list(ImageRecord.find(session, deleted=deleted, limit=limit))
#
#   @router.get("/images/similar", response_model=list[LifelogImage])
#   def similar_images(
#       image_path: str,
#       session: Session = Depends(get_session),
#   ):
#       src = ImageRecord.find_one(session, image_path=image_path)
#       if not src:
#           raise HTTPException(404)
#       # Load embedding from DB directly
#       from sqlalchemy import select
#       from models import Image
#       row = session.execute(
#           select(Image).where(Image.image_path == image_path)
#       ).scalars().first()
#       if row.embedding is None:
#           raise HTTPException(422, "No embedding for this image")
#       return [img for img, _ in ImageRecord.find_similar(session, list(row.embedding))]


# ---------------------------------------------------------------------------
# DaySummaryRecord — stub, implement if needed
# ---------------------------------------------------------------------------
class DaySummaryRecord(Document, DaySummary):
    class ODMConfig(Document.ODMConfig):
        collection_name = "day_summaries"

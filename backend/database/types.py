from __future__ import annotations
import time

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
    distinct as sa_distinct,
)
from collections import Counter
from sqlalchemy.orm import Session
from mongodb_odm import Document

from app_types import DaySummary, GPSInfo, LifelogImage, LocationInfo, ResultSegment
from database.models import Image, ImageGPS, Location


DICT_TYPE = Dict[str, Any]
SORT_TYPE = Union[str, Sequence[Tuple[str, Union[int, str, Mapping[str, Any]]]]]
DocumentType = TypeVar("DocumentType", bound=Mapping[str, Any])


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def _orm_to_lifelog(row: Image) -> LifelogImage:
    """Convert a SQLAlchemy Image row → LifelogImage Pydantic model."""
    return LifelogImage.model_validate(row.__dict__)

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

        now = time.time()
        rows = session.execute(stmt).scalars().all()
        print(f"Query returned {len(rows)} rows in {time.time() - now:.2f} seconds")

        for row in rows:
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
    # Vector / face / GPS searches — new capabilities
    # ------------------------------------------------------------------
    @classmethod
    def find_segments(
        cls,
        session: Session,
        date: str,
        device: str,
        deleted: bool = False,
        page: int = 0,
        page_size: int = 20,
        hour: str = "",
        today: bool = False,
    ) -> Dict[str, Any]:
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
        # Step 1: find all matching images
        stmt = (
            select(Image)
                .where(Image.date == date)
                .where(Image.device == device)
                .where(Image.deleted == deleted)
            )

        if hour:
            stmt = stmt.where(Image.hour == str(hour).zfill(2))

        stmt = stmt.order_by(asc(Image.segment_id), asc(Image.timestamp))
        rows = session.execute(stmt).scalars().all()

        # Step 2: group in Python (avoids complex lateral join)
        grouped: dict[Any, list[Image]] = {}
        for row in rows:
            key = row.segment_id
            if key not in grouped:
                grouped[key] = []
            grouped[key].append(row)

        # Step 3: sort segment keys descending (mirrors $sort: {_id: -1})
        sorted_keys = sorted(
            grouped.keys(),
            key=lambda k: (k is None, k if k is not None else 0),
            reverse=today,
        )

        # Step 4: paginate
        total_pages = max(1, (len(sorted_keys) + page_size - 1) // page_size)
        paginated_keys = sorted_keys[page * page_size : (page + 1) * page_size]
        segments = []

        all_images = set()
        for key in paginated_keys:
            images = grouped[key]
            images = sorted(images, key=lambda img: img.timestamp, reverse=False)  # type: ignore
            image_paths = [img.image_path for img in images]
            stmt = select(Location).join(Image.location).where(Image.image_path.in_(image_paths))
            locations = session.execute(stmt).scalars().all()
            locations = [loc for loc in locations if loc is not None]
            # get the most common location for this segment (if any)
            location = None
            if locations:
                location_counts = Counter([str(loc.id) for loc in locations])
                most_common_id, _ = location_counts.most_common(1)[0]
                location = next((loc for loc in locations if str(loc.id) == most_common_id), None)

            images = [ _orm_to_lifelog(img) for img in images]
            all_images.update(image_paths)

            try:
                gps_info = [GPSInfo.model_validate(g.__dict__) for g in session.execute(select(ImageGPS).where(Image.image_path.in_(image_paths)).join(ImageGPS.image).order_by(Image.timestamp.desc())).scalars().all()]
                segments.append(
                    ResultSegment(
                        segment_id=key,
                        images=images,
                        location=LocationInfo.model_validate(location.__dict__) if location else None,
                        gps=gps_info,
                    )
                )
            except Exception as e:
                segments.append(
                    ResultSegment(
                        segment_id=key,
                        images=images,
                    )
                )

        # Step 5: Get GPS data
        segment_gps = session.execute(
            select(ImageGPS)
            .where(Image.date == date)
            .where(Image.deleted == False)
            .where(Image.device == device)
            .where(Image.image_path.in_(all_images))
            .join(Image.gps)
            .order_by(Image.timestamp.desc())
        ).scalars().all()
        gps = [GPSInfo.model_validate(g.__dict__) for g in segment_gps]

        # Step 6: convert to desired output format
        return {
            "segments": segments,
            "gps": gps,
            "total_pages": total_pages,
        }





# ---------------------------------------------------------------------------
# DaySummaryRecord
# ---------------------------------------------------------------------------
class DaySummaryRecord(Document, DaySummary):
    class ODMConfig(Document.ODMConfig):
        collection_name = "day_summaries"

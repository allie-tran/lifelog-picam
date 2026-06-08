from __future__ import annotations
import logging
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

logger = logging.getLogger(__name__)

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

        t0 = time.time()
        rows = session.execute(stmt).scalars().all()
        logger.debug("ImageRecord.find returned %d rows in %.2fs", len(rows), time.time() - t0)

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
        """
        # Step 1: fetch all matching images for the date (uses composite index)
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

        # Step 2: group in Python by segment_id
        grouped: dict[Any, list[Image]] = {}
        for row in rows:
            key = row.segment_id
            if key not in grouped:
                grouped[key] = []
            grouped[key].append(row)

        # Step 3: sort segment keys
        sorted_keys = sorted(
            grouped.keys(),
            key=lambda k: (k is None, k if k is not None else 0),
            reverse=today,
        )

        # Step 4: paginate segment keys
        total_pages = max(1, (len(sorted_keys) + page_size - 1) // page_size)
        paginated_keys = sorted_keys[page * page_size : (page + 1) * page_size]

        # Step 5: batch-fetch locations and GPS for all images on this page
        # (2 queries for the whole page instead of 2 per segment)
        page_key_paths: dict[Any, list[str]] = {}
        all_page_paths: list[str] = []
        for key in paginated_keys:
            paths = [img.image_path for img in grouped[key]]
            page_key_paths[key] = paths
            all_page_paths.extend(paths)

        path_to_location: dict[str, Location] = {}
        path_to_gps: dict[str, list[ImageGPS]] = {}

        if all_page_paths:
            # One location query for the entire page
            for path, loc in session.execute(
                select(Image.image_path, Location)
                .join(Image.location)
                .where(Image.image_path.in_(all_page_paths))
            ).all():
                path_to_location[path] = loc

            # One GPS query for the entire page
            for path, gps_row in session.execute(
                select(Image.image_path, ImageGPS)
                .join(ImageGPS.image)
                .where(Image.image_path.in_(all_page_paths))
                .order_by(Image.timestamp.desc())
            ).all():
                path_to_gps.setdefault(path, []).append(gps_row)

        # Step 6: assemble segments from pre-fetched data (no extra DB calls)
        segments = []
        all_images: set[str] = set()

        for key in paginated_keys:
            images_orm = grouped[key]
            images_orm = sorted(images_orm, key=lambda img: img.timestamp or 0, reverse=False)
            image_paths = page_key_paths[key]

            # Most-common location for this segment
            seg_locs = [path_to_location[p] for p in image_paths if p in path_to_location]
            location = None
            if seg_locs:
                location_counts = Counter(str(loc.id) for loc in seg_locs)
                most_common_id, _ = location_counts.most_common(1)[0]
                location = next((loc for loc in seg_locs if str(loc.id) == most_common_id), None)

            # GPS points for this segment
            gps_info = [
                GPSInfo.model_validate(g.__dict__)
                for p in image_paths
                for g in path_to_gps.get(p, [])
            ]

            images = [_orm_to_lifelog(img) for img in images_orm]
            if today:
                images = images[::-1]
            all_images.update(image_paths)

            segments.append(
                ResultSegment(
                    segment_id=key,
                    images=images,
                    location=LocationInfo.model_validate(location.__dict__) if location else None,
                    gps=gps_info,
                )
            )

        # Step 7: build the day-level GPS track from already-fetched data (no extra query)
        gps_flat = [g for p in all_images for g in path_to_gps.get(p, [])]
        gps_flat.sort(key=lambda g: g.timestamp or 0, reverse=True)
        gps = [GPSInfo.model_validate(g.__dict__) for g in gps_flat]

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

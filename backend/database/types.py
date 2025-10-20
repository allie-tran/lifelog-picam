from mongodb_odm import Document, IndexModel
from typing import (
    Any,
    Dict,
    Iterator,
    Mapping,
    Optional,
    Sequence,
    Tuple,
    TypeVar,
    Union,
)

from bson import ObjectId as _ObjectId
from mongodb_odm.models import INHERITANCE_FIELD_NAME, Document
from pydantic import BaseModel, field_serializer
from pydantic import BaseModel, computed_field, field_serializer
from dependencies import CamelCaseModel


class ObjectDetection(BaseModel):
    label: str
    confidence: float
    bbox: list[int]  # [x_min, y_min, x_max, y_max]
    embedding: Optional[list[float]] = None


DICT_TYPE = Dict[str, Any]
SORT_TYPE = Union[str, Sequence[Tuple[str, Union[int, str, Mapping[str, Any]]]]]

DocumentType = TypeVar("DocumentType", bound=Mapping[str, Any])


class ProcessedInfo(BaseModel):
    yolo: bool = False
    face_recognition: bool = False
    encoded: bool = False

class ImageRecord(Document, CamelCaseModel):
    image_path: str # YYYY-MM-DD/YYMMDD_HHMMSS.jpg
    timestamp: float  # ISO 8601 format
    thumbnail: str
    is_video: bool

    objects: list[ObjectDetection] = []
    people: list[ObjectDetection] = []

    deleted: bool = False

    date: str

    segment_id: Optional[int] = None
    activity: str = ""

    processed: ProcessedInfo = ProcessedInfo()

    @computed_field
    @property
    def hour(self) -> str:
        return self.image_path.split("_")[1][:2]


    @classmethod
    def _get_collection_name(cls) -> str:
        return "images"

    class ODMConfig(Document.ODMConfig):
        allow_inheritance = False
        collection_name = "images"
        indexes = [
            IndexModel([("image_path", 1)], unique=True),
            IndexModel([("timestamp", -1)]),
            IndexModel([("deleted", 1)]),
            IndexModel([("segment_id", 1)]),
        ]

    @field_serializer("id", "_id", mode="plain", check_fields=False)
    def serialize_object_id(self, value: _ObjectId) -> str:
        return str(value)

    @classmethod
    def find(
        cls,
        filter: Optional[DICT_TYPE] = None,
        projection: Optional[DICT_TYPE] = None,
        sort: Optional[SORT_TYPE] = None,
        skip: Optional[int] = None,
        limit: Optional[int] = None,
        distinct: Optional[str] = None,
        **kwargs: Any,
    ) -> Iterator[Any]:
        if filter is None:
            filter = {}

        qs = cls.find_raw(filter, projection, **kwargs)
        if sort:
            qs = qs.sort(sort)
        if skip:
            qs = qs.skip(skip)
        if limit:
            qs = qs.limit(limit)
        if distinct:
            qs = qs.distinct(distinct)
            for data in qs:
                yield data
            return

        if cls._has_children():
            model_children = {}
            for model in cls.__subclasses__():
                model_children[model._get_child()] = model

            for data in qs:
                if data.get(INHERITANCE_FIELD_NAME) in model_children:
                    """If this is a child model then convert it to that child model."""
                    yield model_children[data[INHERITANCE_FIELD_NAME]](**data)
                else:
                    """Convert it to the parent model"""
                    yield cls(**data)

        for data in qs:
            yield cls(**data)


from collections import defaultdict
from enum import Enum
from datetime import datetime
from typing import (
    Annotated,
    Any,
    Callable,
    ClassVar,
    Dict,
    Generic,
    List,
    Literal,
    Optional,
    TypeVar,
    NamedTuple,
)

import numpy as np
import numpy.typing as npt
from fastapi import FastAPI
from pydantic import BaseModel, Field, GetPydanticSchema, InstanceOf, computed_field, field_validator
from sqlalchemy import UUID
from typing_extensions import TypeAlias

from dependencies import CamelCaseModel

DType = TypeVar("DType", bound=np.generic)

Array1D = Annotated[npt.NDArray[DType], Literal["N"]]
Array2D = Annotated[npt.NDArray[DType], Literal["N", "N"]]
Array4 = Annotated[npt.NDArray[DType], Literal[4]]
Array3x3 = Annotated[npt.NDArray[DType], Literal[3, 3]]
ArrayNxNx3 = Annotated[npt.NDArray[DType], Literal["N", "N", 3]]

RootDictType = TypeVar("RootDictType", bound=BaseModel)


class DictRootModel(BaseModel, Generic[RootDictType]):
    root: Dict[str, RootDictType] = Field(default_factory=dict)
    _default_factory: ClassVar[Callable[[], RootDictType]]

    def __init__(self):
        super().__init__(root={})

    def __getitem__(self, key: str) -> RootDictType:
        if key not in self.root.keys():
            # create and store default
            return self._default_factory()
        return self.root[key]

    def __setitem__(self, key: str, value: RootDictType) -> None:
        self.root[key] = value

    def keys(self):
        return self.root.keys()

    def values(self):
        return self.root.values()

    def items(self):
        return self.root.items()


PydanticNDArray: TypeAlias = Annotated[
    Array2D[np.float32],
    GetPydanticSchema(
        lambda _s, h: h(InstanceOf[np.ndarray]), lambda _s, h: h(InstanceOf[np.ndarray])
    ),
]


class CLIPFeatures(BaseModel):
    # features: PydanticNDArray = Field(
    #     default_factory=lambda: np.empty((0, 512), dtype=np.float32)
    # )
    # image_paths: list[str] = []
    # image_paths_to_index: Dict[str, int] = {}
    collection: Optional[Any] = None  # Placeholder for the zvec collection object


class DeviceFeatures(DictRootModel[CLIPFeatures]):
    _default_factory: ClassVar[Callable[[], CLIPFeatures]] = CLIPFeatures


class AppFeatures(DictRootModel[DeviceFeatures]):
    _default_factory: ClassVar[Callable[[], DeviceFeatures]] = DeviceFeatures


class CustomFastAPI(FastAPI):
    models: List[str] = ["conclip"]
    features: AppFeatures = AppFeatures.model_validate({})

    retrieved_videos: Dict[str, np.ndarray] = defaultdict(
        lambda: np.array([], dtype=np.float32)
    )
    normalizing_sum: Dict[str, np.ndarray] = defaultdict(
        lambda: np.array([], dtype=np.float32)
    )
    low_visual_indices: Dict[str, np.ndarray] = defaultdict(
        lambda: np.array([], dtype=np.int32)
    )
    images_with_low_density: set[str] = set()

    segments: Dict[str, list[list[str]]] = defaultdict(
        list
    )  # device_id -> list of segments (each segment is a list of image paths)
    image_to_segment: Dict[str, dict[str, int]] = defaultdict(
        dict
    )  # device_id -> (image_path -> segment_index)

    last_saved: datetime = datetime.now()


class ObjectDetection(BaseModel):
    label: str
    confidence: float
    bbox: list[int]  # [x_min, y_min, x_max, y_max]
    rel_bbox: Optional[list[float]] = None  # [x_min_rel, y_min_rel, x_max_rel, y_max_rel]
    embedding: Optional[list[float]] = None
    cluster_label: Optional[int] = None


class ProcessedInfo(BaseModel):
    yolo: bool = False
    face_recognition: bool = False
    encoded: bool = False
    sam3: bool = False


class GPSInfo(BaseModel):
    latitude: float
    longitude: float
    elevation: Optional[float] = None


class LocationInfo(CamelCaseModel):
    id: Optional[str] = None
    name: Optional[str] = None
    info: Optional[str] = None
    address: Optional[str] = None
    country: str
    timezone: str
    latitude: Optional[float] = None
    longitude: Optional[float] = None

    @field_validator("id", mode="before")
    @classmethod
    def parse_id(cls, id: Any) -> Optional[str]:
        try:
            return str(id)
        except (ValueError, TypeError):
            return None


class LifelogImage(CamelCaseModel):
    device: str
    image_path: str  # YYYY-MM-DD/YYMMDD_HHMMSS.jpg
    timestamp: datetime
    local_timestamp: Optional[datetime] = None
    seconds_from_midnight: int = Field(
        default=0, ge=0, lt=24 * 3600
    )
    thumbnail: str
    is_video: bool

    deleted: bool = False
    deleted_time: Optional[datetime] = None

    date: str
    hour: int

    segment_id: Optional[int] = None
    activity: Optional[str] = None
    activity_description: Optional[str] = None
    activity_confidence: Optional[str] = None

    new: bool = True


class ResultSegment(CamelCaseModel):
    segment_id: Optional[int] = None
    images: list[LifelogImage]
    location: Optional[LocationInfo] = None
    gps: list[GPSInfo] = []

class SummarySegment(CamelCaseModel):
    segment_index: int | None = None
    activity: str
    start_time: datetime
    end_time: datetime
    duration: int
    representative_image: LifelogImage | None = None
    representative_images: list[LifelogImage] = []


class ActionType(str, Enum):
    BURST = "burst"  # Frequency: e.g., "drinking water"
    PERIOD = "period"  # Duration/Segments: e.g., "eating"
    BINARY = "binary"  # State: e.g., "social vs alone"


class CustomTarget(NamedTuple):
    name: str
    action_type: ActionType
    query_prompt: str  # The prompt for CLIP/Classifier


class DaySummary(CamelCaseModel):
    date: str
    segments: List[SummarySegment] = []
    summary_text: str = ""
    updated: bool = False
    device: str = ""

    # 1. BINARY: Tracks durations for "state" targets (e.g., "social_minutes": 120.0)
    # Replaces: social_minutes, alone_minutes
    binary_metrics: Dict[str, float] = Field(default_factory=dict)

    # 2. PERIODS: Stores groups of segments for specific activities (e.g., "eating")
    # Replaces: food_drink_segments, food_drink_minutes
    period_metrics: Dict[str, List[SummarySegment]] = Field(default_factory=dict)

    # 3. BURSTS: Lists of timestamps/counts for instant actions (e.g., "drinking water")
    burst_metrics: Dict[str, List[float]] = Field(default_factory=dict)

    # Summaries for specific periods (e.g., {"Dining": "Quick lunch at desk"})
    # Replaces: food_drink_summary
    custom_summaries: Dict[str, str] = Field(default_factory=dict)

    # Bookkeeping
    category_minutes: Dict[str, float] = {}
    total_images: int = 0
    total_minutes: float = 0.0

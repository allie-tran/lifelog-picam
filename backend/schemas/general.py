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
from pydantic import BaseModel, BeforeValidator, Field, GetPydanticSchema, InstanceOf, computed_field, field_validator
from sqlalchemy import UUID
from typing_extensions import TypeAlias

from core.dependencies import CamelCaseModel


def _nan_to_none(value: Any) -> Optional[float]:
    """Coerce NaN/inf floats (e.g. from numpy/GPS sources) to None."""
    if isinstance(value, float) and (np.isnan(value) or np.isinf(value)):
        return None
    return value


# Reusable latitude/longitude field type: parses NaN/inf -> None.
Coordinate: TypeAlias = Annotated[Optional[float], BeforeValidator(_nan_to_none)]


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
    cluster_id: Optional[str] = None


class ProcessedInfo(BaseModel):
    yolo: bool = False
    face_recognition: bool = False
    encoded: bool = False
    sam3: bool = False


class GPSInfo(BaseModel):
    latitude: Coordinate
    longitude: Coordinate
    elevation: Optional[float] = None
    timestamp: Optional[float] = None  # ms epoch (UTC)


class LocationInfo(CamelCaseModel):
    id: Optional[str] = None
    name: Optional[str] = None
    stop: Optional[bool] = None
    # admin hierarchy
    suburb: Optional[str] = None
    city: Optional[str] = None
    region: Optional[str] = None
    country: str
    postcode: Optional[str] = None
    # geocoder output
    address: Optional[str] = None
    timezone: str
    latitude: Coordinate = None
    longitude: Coordinate = None
    # enrichment
    wikidata_id: Optional[str] = None
    description: Optional[str] = None
    categories: Optional[str] = None
    # legacy (may be null on new records)
    info: Optional[str] = None
    # visit count (populated by list/search endpoints)
    count: Optional[int] = None

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
    timezone: str | None = None
    local_timestamp: Optional[datetime] = None
    seconds_from_midnight: int = Field(
        default=0, ge=0, lt=24 * 3600
    )
    thumbnail: str | None
    grid_thumbnail: str | None = None  # small derivative for grids (see services.utils)
    is_video: bool

    deleted: bool = False
    deleted_time: Optional[datetime] = None

    date: str
    hour: int

    segment_id: Optional[int] = None
    activity: Optional[str] = None
    activity_group: Optional[str] = None
    activity_description: Optional[str] = None
    activity_confidence: Optional[str] = None
    activity_tags: Optional[str] = None

    new: bool = True


class GridImage(CamelCaseModel):
    """Slim image payload for the browse grid. Only the fields the frontend
    actually renders — drops device/date/hour/localTimestamp/secondsFromMidnight/
    deleted/deletedTime/activityTags that LifelogImage carries but the grid never
    reads, to keep day/segment responses small."""
    image_path: str
    thumbnail: str | None = None
    grid_thumbnail: str | None = None  # small derivative for the grid (see services.utils)
    timestamp: datetime
    timezone: str | None = None
    is_video: bool = False
    segment_id: Optional[int] = None
    activity: Optional[str] = None
    activity_group: Optional[str] = None
    activity_description: Optional[str] = None
    activity_confidence: Optional[str] = None
    new: bool = True


class ResultSegment(CamelCaseModel):
    segment_id: Optional[int] = None
    images: list[GridImage]
    location: Optional[LocationInfo] = None
    gps: list[GPSInfo] = []

class FoodItem(CamelCaseModel):
    name: str
    portion: str = ""            # rough amount, e.g. "bowl", "2 slices"
    calories: Optional[int] = None  # rough estimate


class MealFood(CamelCaseModel):
    """Structured food detail for one eating segment (from the food pass)."""
    meal_type: Optional[str] = None   # breakfast | lunch | dinner | snack
    items: List[FoodItem] = Field(default_factory=list)
    total_calories: Optional[int] = None
    healthiness: Optional[str] = None
    summary: Optional[str] = None


class DayFood(CamelCaseModel):
    """Per-day food rollup aggregated from the day's MealFood records."""
    meal_count: int = 0
    total_calories: Optional[int] = None
    items: List[str] = Field(default_factory=list)   # flat list of item names
    meals: List[MealFood] = Field(default_factory=list)


class SummarySegment(CamelCaseModel):
    segment_id: Optional[int] = None   # DB segment_id — used for incremental cache updates
    segment_index: int | None = None
    activity: str = "Unclear"
    activity_group: Optional[str] = None
    activity_tags: Optional[str] = None  # comma-separated canonical activity names from LLM
    start_time: datetime
    end_time: datetime
    duration: int
    representative_image: LifelogImage | None = None
    representative_images: list[LifelogImage] = []
    avg_hr: Optional[float] = None
    hr_zone: Optional[str] = None
    location_name: Optional[str] = None
    location_stop: Optional[bool] = None
    location_latitude: Coordinate = None
    location_longitude: Coordinate = None
    # IANA zone of the capture (start_time/end_time are naive UTC — the frontend
    # converts UTC→this zone for display, so it shows local wall-clock, not UTC).
    timezone: Optional[str] = None
    # Structured food detail, present on eating segments (from the food pass).
    food: Optional[MealFood] = None


class LocationVisit(CamelCaseModel):
    """
    A visit = a maximal run of consecutive segments that share the same
    location (a single stop / place). One natural-language description is
    generated per visit — coarser than per-segment, so the day reads as a
    sequence of places rather than 10-minute slices.
    """
    visit_index: int = 0
    location_name: Optional[str] = None
    location_stop: Optional[bool] = None
    location_latitude: Coordinate = None
    location_longitude: Coordinate = None
    start_time: datetime
    end_time: datetime
    duration: int = 0  # seconds
    timezone: Optional[str] = None  # IANA zone for UTC→local display (see SummarySegment)
    segment_ids: List[int] = Field(default_factory=list)
    segment_indices: List[int] = Field(default_factory=list)
    activity_groups: List[str] = Field(default_factory=list)
    description: str = ""
    # Non-empty when online current-events grounding was used for a notable venue.
    event_context: Optional[str] = None
    representative_image: LifelogImage | None = None


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
    number_of_images: int = 0
    last_image_time: Optional[datetime] = None

    segments: List[SummarySegment] = []
    location_visits: List[LocationVisit] = []
    # Signature of the segments the location_visits were built from. Lets a
    # rebuild reuse existing visits (skip the LLM/web-search) when segments are
    # unchanged, so a late GPS upload / text refresh no longer wipes them.
    location_visits_sig: Optional[str] = None
    summary_text: str = ""
    updated: bool = False
    device: str = ""

    # Incremental rebuild flags
    dirty_segment_ids: List[int] = Field(default_factory=list)
    text_summary_stale: bool = False
    is_live: bool = False  # True when date==today and capture is still active

    # Daily biometrics
    avg_hr: Optional[float] = None
    resting_hr: Optional[float] = None
    max_hr: Optional[float] = None
    rmssd: Optional[float] = None
    step_count: Optional[int] = None
    sleep_start: Optional[datetime] = None
    sleep_end: Optional[datetime] = None
    sleep_minutes: Optional[int] = None

    # 1. BINARY: Tracks durations for "state" targets (e.g., "social_minutes": 120.0)
    binary_metrics: Dict[str, float] = Field(default_factory=dict)

    # 2. PERIODS: Stores groups of segments for specific activities (e.g., "eating")
    period_metrics: Dict[str, List[SummarySegment]] = Field(default_factory=dict)

    # 3. BURSTS: Lists of timestamps/counts for instant actions (e.g., "drinking water")
    burst_metrics: Dict[str, List[float]] = Field(default_factory=dict)

    # Summaries for specific periods (e.g., {"Dining": "Quick lunch at desk"})
    custom_summaries: Dict[str, str] = Field(default_factory=dict)

    # Per-day food rollup (eating focus), aggregated from segment food records.
    food: Optional[DayFood] = None

    # What made this day unique (generated by novelty analysis)
    unique_highlight: str = ""
    novelty_segments: List[int] = Field(default_factory=list)  # segment_ids of novel moments

    # Bookkeeping
    category_minutes: Dict[str, float] = {}
    total_images: int = 0
    total_minutes: float = 0.0
    analysis_checkpoint: Optional[str] = None  # image_path of last CLIP-analyzed image
    processing: bool = False  # True while a background rebuild task is running
    text_summary_generated_at: Optional[datetime] = None  # last time LLM text was generated


# ---------------------------------------------------------------------------
# Multi-day period summaries (week / month / trip / custom) — a hierarchy on
# top of the per-day DaySummary. The day is the atomic unit; a period rolls up
# the DaySummary records in its span. Higher levels summarize the highlights of
# the level below.
# ---------------------------------------------------------------------------
class TopLocation(CamelCaseModel):
    """A place visited during the period, aggregated across its days."""
    name: str
    latitude: Coordinate = None
    longitude: Coordinate = None
    days: int = 0          # distinct days the place was visited
    visits: int = 0        # total visit count across the period
    minutes: float = 0.0   # total minutes spent
    representative_image: Optional[LifelogImage] = None


class BioTrendPoint(CamelCaseModel):
    date: str
    sleep_minutes: Optional[int] = None
    avg_hr: Optional[float] = None
    step_count: Optional[int] = None


class BioTrend(CamelCaseModel):
    avg_sleep_minutes: Optional[float] = None
    avg_hr: Optional[float] = None
    resting_hr: Optional[float] = None
    max_hr: Optional[float] = None
    avg_steps: Optional[float] = None
    series: List[BioTrendPoint] = Field(default_factory=list)


class TrendItem(CamelCaseModel):
    """A single behavioural change vs the previous comparable period."""
    metric: str                        # e.g. "Leisure & Wellbeing", "sleep_minutes"
    current: Optional[float] = None
    previous: Optional[float] = None
    delta: Optional[float] = None      # current - previous
    direction: str = "flat"            # "up" | "down" | "flat" | "new" | "gone"
    note: str = ""                     # short human phrasing


class PeriodSummary(CamelCaseModel):
    kind: str                          # "week" | "month" | "trip" | "custom"
    device: str = ""
    start_date: str                    # YYYY-MM-DD inclusive
    end_date: str                      # YYYY-MM-DD inclusive
    label: str = ""

    day_dates: List[str] = Field(default_factory=list)   # days actually in the span
    active_days: int = 0               # days with any captured activity

    # Hierarchy pointers: children this period rolls up (week->days, month->weeks)
    child_kind: str = "day"
    child_keys: List[str] = Field(default_factory=list)

    # Roll-ups
    category_minutes: Dict[str, float] = Field(default_factory=dict)
    total_minutes: float = 0.0
    total_images: int = 0
    binary_totals: Dict[str, float] = Field(default_factory=dict)
    burst_totals: Dict[str, int] = Field(default_factory=dict)

    top_locations: List[TopLocation] = Field(default_factory=list)
    bio_trend: Optional[BioTrend] = None

    summary_text: str = ""
    highlights: List[str] = Field(default_factory=list)
    trends: List[TrendItem] = Field(default_factory=list)

    # Bookkeeping
    updated: bool = False
    processing: bool = False
    generated_at: Optional[datetime] = None
    # Hash of the child days' (date, text_summary_generated_at, updated). Lets a
    # fetch reuse the cached period unless an underlying day actually changed.
    source_sig: Optional[str] = None


# ---------------------------------------------------------------------------
# Chat assistant — a conversation the user has about their days. The bot can
# answer questions and auto-apply edits (segment activity, day summary text,
# location label) via tool-calls, and maintains a distilled memory of durable
# facts. Transcripts persist per thread; a day thread is keyed {device}:{date}.
# ---------------------------------------------------------------------------
class TokenUsage(CamelCaseModel):
    prompt: int = 0
    completion: int = 0
    total: int = 0


class AppliedAction(CamelCaseModel):
    """A tool-call the bot executed during a turn — surfaced so the UI can show
    what changed and refresh the affected day/period view."""
    tool: str
    args: Dict[str, Any] = Field(default_factory=dict)
    outcome: str = ""


class ChatMessage(CamelCaseModel):
    role: str                       # "user" | "assistant" | "tool"
    content: str = ""
    # Present on assistant turns that invoked tools (for transcript replay).
    applied_actions: List[AppliedAction] = Field(default_factory=list)
    token_usage: Optional[TokenUsage] = None
    ts: datetime = Field(default_factory=datetime.utcnow)


class ChatThread(CamelCaseModel):
    thread_id: str
    username: str = ""
    device: str = ""
    scope: str = "day"              # "day" | "global"
    date: Optional[str] = None      # set for day-scoped threads
    messages: List[ChatMessage] = Field(default_factory=list)
    token_usage: TokenUsage = Field(default_factory=TokenUsage)
    created: datetime = Field(default_factory=datetime.utcnow)
    updated: datetime = Field(default_factory=datetime.utcnow)


class ChatMemory(CamelCaseModel):
    """One durable fact the bot maintains about the user, injected into every
    future turn's system prompt. Keyed by (username, device, key)."""
    username: str = ""
    device: str = ""
    key: str
    text: str = ""
    updated: datetime = Field(default_factory=datetime.utcnow)


class ChatMessageRequest(CamelCaseModel):
    scope: str = "day"
    date: Optional[str] = None
    thread_id: Optional[str] = None
    text: str


class MemoryUpsertRequest(CamelCaseModel):
    key: str
    text: str


class ChatTurnResponse(CamelCaseModel):
    thread_id: str
    reply: str
    applied_actions: List[AppliedAction] = Field(default_factory=list)
    message_usage: TokenUsage = Field(default_factory=TokenUsage)
    total_usage: TokenUsage = Field(default_factory=TokenUsage)
    # Durable facts auto-captured from this turn (surfaced as "remembered …").
    distilled: List[ChatMemory] = Field(default_factory=list)

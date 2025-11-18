from typing import Annotated, Dict, Literal, TypeVar
from fastapi import FastAPI
from datetime import datetime
import numpy as np
import numpy.typing as npt
from collections import defaultdict

from dependencies import CamelCaseModel


DType = TypeVar("DType", bound=np.generic)

Array1D = Annotated[npt.NDArray[DType], Literal["N"]]
Array2D = Annotated[npt.NDArray[DType], Literal["N", "N"]]
Array4 = Annotated[npt.NDArray[DType], Literal[4]]
Array3x3 = Annotated[npt.NDArray[DType], Literal[3, 3]]
ArrayNxNx3 = Annotated[npt.NDArray[DType], Literal["N", "N", 3]]

class CustomFastAPI(FastAPI):
    features: Dict[str, Array2D[np.float64 | np.float32]]
    image_paths: Dict[str, list[str]]

    retrieved_videos: Dict[str, np.ndarray]  # Indices of retrieved videos for QB norm
    normalizing_sum: Dict[str, np.ndarray]  # Normalizing sum for QB norm
    low_visual_indices: Dict[str, np.ndarray]  # Indices of low visual density images
    images_with_low_density: set[str] = set()

    segments: Dict[str, list[list[str]]] = defaultdict(list)
    image_to_segment: Dict[str, dict[str, int]] = defaultdict(dict)

    last_saved: datetime = datetime.now()


class SummarySegment(CamelCaseModel):
    segment_index: int | None = None
    activity: str
    start_time: str
    end_time: str
    duration: int

class DaySummary(CamelCaseModel):
    date: str
    segments: list[SummarySegment] = []
    summary_text: str = ""
    updated: bool = False
    device: str = ""

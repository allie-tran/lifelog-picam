from __future__ import annotations
from datetime import datetime
from typing import List, Optional, Literal, Tuple
from pydantic import BaseModel, Field, computed_field

from app_types.general import LocationInfo
from dependencies import CamelCaseModel

class GeoProximity(BaseModel):
    lat: float = Field(..., ge=-90, le=90)
    lon: float = Field(..., ge=-180, le=180)
    radius_km: float = Field(default=1.0, gt=0)

class TimeRange(BaseModel):
    start: Optional[datetime] = None
    end: Optional[datetime] = None


TimeOfDay = Literal["morning", "afternoon", "evening", "night", "midday"]
DayOfWeek = Literal["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]
MonthOfYear = Literal["January", "February", "March", "April", "May", "June", "July", "August", "September", "October", "November", "December"]

class TimeDayCell(CamelCaseModel):
    time_of_day: TimeOfDay
    day_of_week: DayOfWeek

class TimeMonthCell(CamelCaseModel):
    time_of_day: TimeOfDay
    month: MonthOfYear


class SearchQuery(CamelCaseModel):
    # Text Search
    text: str = ""
    image_path: Optional[str] = None
    is_image_query: bool = False

    # time — row/col (broad) selectors
    time_of_days: List[TimeOfDay] = []
    day_of_weeks: List[DayOfWeek] = []
    seasons: List[Literal["spring", "summer", "autumn", "winter"]] = []
    months: List[MonthOfYear] = []
    years: List[int] = []
    custom_ranges: List[TimeRange] = []

    # time — individual cell selectors (OR'd with row/col selectors)
    time_day_cells: List[TimeDayCell] = []
    time_month_cells: List[TimeMonthCell] = []

    # location
    is_moving: bool = False
    countries: List[str] = []
    location_ids: List[str] = []
    bounds: Optional[List[float]] = None  # [min_lat, min_lon, max_lat, max_lon]

    # people
    people_ids: List[str] = []

    @computed_field
    @property
    def empty(self) -> bool:
        return not any([
            self.text,
            self.image_path,
            self.time_of_days,
            self.day_of_weeks,
            self.months,
            self.years,
            self.custom_ranges,
            self.time_day_cells,
            self.time_month_cells,
            self.countries,
            self.location_ids,
            self.bounds,
            self.people_ids
        ])


class ResultSummary(CamelCaseModel):
    total_images: int
    total_segments: int = 0

    # time breakdowns
    time_of_days: List[Tuple[TimeOfDay, int]] = []
    day_of_weeks: List[Tuple[DayOfWeek, int]] = []
    seasons: List[Tuple[Literal["spring", "summer", "autumn", "winter"], int]] = []
    months: List[Tuple[MonthOfYear, int]] = []
    years: List[Tuple[int, int]] = []
    custom_ranges: List[Tuple[TimeRange, int]] = []

    # location breakdowns
    locations: List[Tuple[LocationInfo, int]] = []
    countries: List[Tuple[str, int]] = []

    # people breakdowns
    people: List[Tuple[str, int]] = []

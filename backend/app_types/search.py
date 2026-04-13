from __future__ import annotations
from datetime import datetime, date
from typing import List, Optional, Union, Literal
from pydantic import BaseModel, Field

class GeoProximity(BaseModel):
    lat: float = Field(..., ge=-90, le=90)
    lon: float = Field(..., ge=-180, le=180)
    radius_km: float = Field(default=1.0, gt=0)

class TimeRange(BaseModel):
    start: Optional[datetime] = None
    end: Optional[datetime] = None
    gt: Optional[datetime] = Field(None, description="Greater than")
    lt: Optional[datetime] = Field(None, description="Less than")

class BaseFilters(BaseModel):
    # Text Search
    text_query: Optional[str] = None
    location_name: Optional[str] = None

    # Exact Matches
    exact_date: Optional[date] = None
    person_name: Optional[List[str]] = None
    weekdays: Optional[List[Literal["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]]] = None
    month: Optional[int] = Field(None, ge=1, le=12)
    year: Optional[int] = None
    day: Optional[int] = Field(None, ge=1, le=31)

    # Spatiotemporal
    time_range: Optional[TimeRange] = None
    geo_proximity: Optional[GeoProximity] = None

class FilterGroup(BaseModel):
    # Logical Operators
    operator: Literal["AND", "OR", "NOT"] = "AND"
    conditions: List[Union[BaseFilters, 'FilterGroup']]

class SearchRequest(BaseModel):
    # The root can be a simple set of filters or a complex logical group
    query: Union[BaseFilters, FilterGroup]

# Required for recursive models in Pydantic
FilterGroup.model_rebuild()

"""
profile.py — per-device user profile settings.

Currently exposes usual meal times, used to drive 'late_meal' notifications.

GET    /profile/meal-times          list configured meal times for a device
PUT    /profile/meal-times          set/override a meal time (marks it manual)
DELETE /profile/meal-times          remove a meal (re-learned automatically later)
POST   /profile/meal-times/relearn  recompute auto meal times from history now
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Annotated, List, Optional

from fastapi import APIRouter, Depends
from sqlalchemy import delete as sa_delete, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from auth import _require_owner
from auth.auth_models import auth_dependency
from auth.types import AccessLevel
from core.dependencies import CamelCaseModel
from database import get_session
from database.models import MealProfile

router = APIRouter()
logger = logging.getLogger(__name__)

_VALID_MEALS = {"breakfast", "lunch", "dinner"}


class MealTimeOut(CamelCaseModel):
    meal: str
    usual_minute: int
    grace_minute: int
    enabled: bool
    auto: bool

    @classmethod
    def from_orm(cls, m: MealProfile) -> "MealTimeOut":
        return cls(
            meal=m.meal,
            usual_minute=m.usual_minute,
            grace_minute=m.grace_minute,
            enabled=m.enabled,
            auto=m.auto,
        )


class MealTimeRequest(CamelCaseModel):
    meal: str
    usual_minute: int
    grace_minute: Optional[int] = None
    enabled: Optional[bool] = None


@router.get("/meal-times", response_model=List[MealTimeOut])
def get_meal_times(
    device: str,
    access_level: Annotated[AccessLevel, Depends(auth_dependency)] = AccessLevel.NONE,
    session: Session = Depends(get_session),
):
    _require_owner(access_level)
    rows = session.execute(
        select(MealProfile)
        .where(MealProfile.device == device)
        .order_by(MealProfile.usual_minute)
    ).scalars().all()
    return [MealTimeOut.from_orm(m) for m in rows]


@router.put("/meal-times")
def put_meal_time(
    request: MealTimeRequest,
    device: str,
    access_level: Annotated[AccessLevel, Depends(auth_dependency)] = AccessLevel.NONE,
    session: Session = Depends(get_session),
):
    _require_owner(access_level)
    meal = request.meal.lower().strip()
    if meal not in _VALID_MEALS:
        return {"error": f"meal must be one of {sorted(_VALID_MEALS)}"}

    minute = max(0, min(1439, request.usual_minute))
    set_values = {"usual_minute": minute, "auto": False, "updated": datetime.now(timezone.utc)}
    if request.grace_minute is not None:
        set_values["grace_minute"] = max(0, request.grace_minute)
    if request.enabled is not None:
        set_values["enabled"] = request.enabled

    stmt = (
        insert(MealProfile)
        .values(
            device=device,
            meal=meal,
            usual_minute=minute,
            grace_minute=request.grace_minute if request.grace_minute is not None else 90,
            enabled=request.enabled if request.enabled is not None else True,
            auto=False,
        )
        .on_conflict_do_update(
            index_elements=["device", "meal"],
            set_=set_values,
        )
    )
    session.execute(stmt)
    session.commit()
    return {"ok": True, "meal": meal}


@router.delete("/meal-times")
def delete_meal_time(
    device: str,
    meal: str,
    access_level: Annotated[AccessLevel, Depends(auth_dependency)] = AccessLevel.NONE,
    session: Session = Depends(get_session),
):
    _require_owner(access_level)
    session.execute(
        sa_delete(MealProfile).where(
            MealProfile.device == device, MealProfile.meal == meal.lower().strip()
        )
    )
    session.commit()
    return {"ok": True}


@router.post("/meal-times/relearn")
def relearn_meal_times(
    device: str,
    access_level: Annotated[AccessLevel, Depends(auth_dependency)] = AccessLevel.NONE,
    session: Session = Depends(get_session),
):
    _require_owner(access_level)
    from services.meals import learn_meal_times

    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    learn_meal_times(session, device, today)
    rows = session.execute(
        select(MealProfile).where(MealProfile.device == device).order_by(MealProfile.usual_minute)
    ).scalars().all()
    return [MealTimeOut.from_orm(m).model_dump(by_alias=True) for m in rows]

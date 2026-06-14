"""
meals.py — usual meal-time learning + late-meal detection.

Two entry points:
  learn_meal_times(session, device)  — derive breakfast/lunch/dinner times
                                       from the last 30 days and upsert them
                                       into meal_profile (auto rows only).
  check_late_meals(session, device, now_local)
                                     — for each enabled meal whose usual time +
                                       grace has passed today with no meal yet
                                       detected, emit a late_meal notification.

A "meal" is inferred from the image activity text matching a small keyword set.
"""
from __future__ import annotations

import logging
import statistics
from datetime import datetime, timedelta
from typing import Optional

from sqlalchemy import func, or_, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from database.models import Image, MealProfile
from services.notify import notify_late_meal

logger = logging.getLogger(__name__)

_LEARN_LOOKBACK_DAYS = 30
_MIN_SAMPLES = 3  # need at least this many meal observations to set a usual time
_DEFAULT_GRACE_MINUTE = 90

# Meal windows in minutes since local midnight: [start, end)
_MEAL_WINDOWS = {
    "breakfast": (4 * 60, 11 * 60),
    "lunch": (11 * 60, 16 * 60),
    "dinner": (16 * 60, 23 * 60),
}

# Activity / location keywords that indicate eating.
_MEAL_KEYWORDS = (
    "eat", "eating", "meal", "breakfast", "brunch", "lunch", "dinner",
    "dining", "food", "restaurant", "cafe", "café", "snack", "cooking",
)


def _meal_activity_filter():
    """SQLAlchemy OR-clause: activity matches any meal keyword (case-insensitive)."""
    return or_(*[Image.activity.ilike(f"%{kw}%") for kw in _MEAL_KEYWORDS])


def _meal_of_minute(minute: int) -> Optional[str]:
    for meal, (start, end) in _MEAL_WINDOWS.items():
        if start <= minute < end:
            return meal
    return None


def learn_meal_times(session: Session, device: str, today: str) -> None:
    """Recompute auto meal times for a device from recent history."""
    cutoff = (
        datetime.strptime(today, "%Y-%m-%d") - timedelta(days=_LEARN_LOOKBACK_DAYS)
    ).strftime("%Y-%m-%d")

    rows = session.execute(
        select(Image.date, Image.seconds_from_midnight)
        .where(
            Image.device == device,
            Image.date >= cutoff,
            Image.date < today,
            Image.deleted == False,
            Image.seconds_from_midnight.isnot(None),
            _meal_activity_filter(),
        )
    ).all()

    # Per (date, meal) take the earliest eating minute, then median across days.
    per_day: dict[tuple[str, str], int] = {}
    for date, secs in rows:
        minute = int(secs) // 60
        meal = _meal_of_minute(minute)
        if meal is None:
            continue
        key = (date, meal)
        if key not in per_day or minute < per_day[key]:
            per_day[key] = minute

    by_meal: dict[str, list[int]] = {}
    for (_, meal), minute in per_day.items():
        by_meal.setdefault(meal, []).append(minute)

    for meal, minutes in by_meal.items():
        if len(minutes) < _MIN_SAMPLES:
            continue
        usual = int(statistics.median(minutes))
        # Upsert only the auto row; never clobber a manual override.
        stmt = (
            insert(MealProfile)
            .values(
                device=device,
                meal=meal,
                usual_minute=usual,
                grace_minute=_DEFAULT_GRACE_MINUTE,
                enabled=True,
                auto=True,
            )
            .on_conflict_do_update(
                index_elements=["device", "meal"],
                set_={"usual_minute": usual},
                where=(MealProfile.auto == True),
            )
        )
        session.execute(stmt)
    session.commit()
    logger.info("Learned meal times for %s: %s", device, list(by_meal.keys()))


def _meal_eaten_today(session: Session, device: str, date: str, meal: str) -> bool:
    start, end = _MEAL_WINDOWS[meal]
    count = session.execute(
        select(func.count(Image.id)).where(
            Image.device == device,
            Image.date == date,
            Image.deleted == False,
            Image.seconds_from_midnight >= start * 60,
            Image.seconds_from_midnight < end * 60,
            _meal_activity_filter(),
        )
    ).scalar_one()
    return count > 0


def check_late_meals(
    session: Session, device: str, date: str, now_minute: int
) -> None:
    """
    For each enabled meal profile whose usual time + grace has elapsed today
    and for which no meal has been detected, emit a late_meal notification.
    """
    profiles = session.execute(
        select(MealProfile).where(
            MealProfile.device == device,
            MealProfile.enabled == True,
        )
    ).scalars().all()

    for p in profiles:
        deadline = p.usual_minute + p.grace_minute
        if now_minute < deadline:
            continue  # not late yet
        _, window_end = _MEAL_WINDOWS.get(p.meal, (0, 24 * 60))
        if now_minute >= window_end:
            continue  # window fully passed; don't nag after the fact
        if _meal_eaten_today(session, device, date, p.meal):
            continue
        notify_late_meal(session, device, date, p.meal, p.usual_minute)
    session.commit()

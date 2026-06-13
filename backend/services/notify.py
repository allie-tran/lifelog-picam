"""
notify.py — generate in-app notifications from pipeline events.

Called from describe_segment_task after a segment is annotated.
Checks two conditions before inserting:
  1. new_location  — location not visited in the past 30 days
  2. unusual_activity — activity not performed in the past 7 days

Uses INSERT … ON CONFLICT DO NOTHING to stay idempotent.
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Optional

from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from database.models import Image, Location, Notification

logger = logging.getLogger(__name__)

_LOCATION_LOOKBACK_DAYS = 30
_ACTIVITY_LOOKBACK_DAYS = 7
_BORING_ACTIVITIES = frozenset({"No Activity", "Unclear Activity", "Unclear", ""})


def _upsert_notification(
    session: Session,
    *,
    device: str,
    date: str,
    segment_id: Optional[int],
    notif_type: str,
    title: str,
    body: str,
    image_path: Optional[str] = None,
    extra: Optional[dict] = None,
) -> None:
    """Insert a notification; silently skips if the same event already exists."""
    stmt = (
        insert(Notification)
        .values(
            device=device,
            date=date,
            segment_id=segment_id,
            type=notif_type,
            title=title,
            body=body,
            image_path=image_path,
            extra=extra,
            read=False,
            timestamp=datetime.now(timezone.utc),
        )
        .on_conflict_do_nothing()
    )
    session.execute(stmt)


def maybe_notify_segment(
    session: Session,
    device: str,
    date: str,
    segment_id: Optional[int],
    activity: Optional[str],
    location_id: Optional[str],
    representative_thumbnail: Optional[str] = None,
) -> None:
    """
    Decide whether the just-annotated segment deserves a notification and create
    one if so.  Safe to call multiple times — uses ON CONFLICT DO NOTHING.
    """
    # ── New location ─────────────────────────────────────────────────────────
    if location_id:
        cutoff = (
            datetime.strptime(date, "%Y-%m-%d") - timedelta(days=_LOCATION_LOOKBACK_DAYS)
        ).strftime("%Y-%m-%d")

        recent_visits = session.execute(
            select(func.count(Image.id))
            .where(
                Image.device == device,
                Image.location_id == location_id,
                Image.date >= cutoff,
                Image.date < date,
                Image.deleted == False,
            )
        ).scalar_one()

        if recent_visits == 0:
            loc = session.get(Location, location_id)
            loc_name = loc.name if loc and loc.name not in ("---", "Unknown Place", "") else (loc.address if loc else "a new place")
            logger.info("New-location notification: %s / %s → %s", device, date, loc_name)
            _upsert_notification(
                session,
                device=device,
                date=date,
                segment_id=segment_id,
                notif_type="new_location",
                title=f"New location: {loc_name}",
                body=f"You visited {loc_name} today for the first time in {_LOCATION_LOOKBACK_DAYS} days.",
                image_path=representative_thumbnail,
                extra={"location_id": str(location_id)},
            )

    # ── Unusual activity ─────────────────────────────────────────────────────
    if activity and activity not in _BORING_ACTIVITIES:
        cutoff = (
            datetime.strptime(date, "%Y-%m-%d") - timedelta(days=_ACTIVITY_LOOKBACK_DAYS)
        ).strftime("%Y-%m-%d")

        recent_count = session.execute(
            select(func.count(Image.id))
            .where(
                Image.device == device,
                Image.activity == activity,
                Image.date >= cutoff,
                Image.date < date,
                Image.deleted == False,
            )
        ).scalar_one()

        if recent_count == 0:
            logger.info("Unusual-activity notification: %s / %s → %s", device, date, activity)
            _upsert_notification(
                session,
                device=device,
                date=date,
                segment_id=segment_id,
                notif_type="unusual_activity",
                title=f"Unusual activity: {activity}",
                body=f"You haven't done '{activity}' in the past {_ACTIVITY_LOOKBACK_DAYS} days.",
                image_path=representative_thumbnail,
                extra={"activity": activity},
            )


def notify_day_complete(
    session: Session,
    device: str,
    date: str,
    summary_text: str = "",
) -> None:
    """
    Called once when all segments for a day are annotated and the summary is ready.
    """
    _upsert_notification(
        session,
        device=device,
        date=date,
        segment_id=None,
        notif_type="day_complete",
        title="Day summary ready",
        body=summary_text[:200] if summary_text else f"Your day summary for {date} is ready.",
    )


def notify_novelty(
    session: Session,
    device: str,
    date: str,
    unique_highlight: str,
    image_path: Optional[str] = None,
) -> None:
    """Called when the novelty analysis generates a unique-day highlight."""
    if not unique_highlight:
        return
    _upsert_notification(
        session,
        device=device,
        date=date,
        segment_id=None,
        notif_type="novelty",
        title="What made today unique",
        body=unique_highlight[:300],
        image_path=image_path,
    )

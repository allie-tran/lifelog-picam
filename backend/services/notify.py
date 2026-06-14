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
_ACTIVITY_LOOKBACK_DAYS = 30
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
    """Insert a notification; silently skips if the same event already exists.

    On a genuinely new insert, also fires a Web Push to the device's browsers.
    """
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
    result = session.execute(stmt)

    # rowcount == 0 means ON CONFLICT skipped it — don't re-push duplicates.
    if result.rowcount:
        # Persist the notification before any push side-effect: a push must only
        # go out for a committed row, and send_to_device() may commit the session
        # when it prunes dead subscriptions — committing here first stops that
        # prune from flushing a half-finished transaction (or a row that later
        # rolls back).
        session.commit()
        try:
            from services.push import send_to_device

            # segment_id keeps the tag distinct per meal slot / segment, so the
            # browser doesn't collapse (renotify) separate same-day alerts —
            # e.g. late breakfast / lunch / dinner no longer overwrite each other.
            send_to_device(
                session,
                device,
                title=title,
                body=body or "",
                tag=f"{notif_type}:{date}:{segment_id}",
            )
        except Exception as e:  # noqa: BLE001 — never let push break the pipeline
            logger.warning("Web push dispatch failed (%s/%s): %s", device, notif_type, e)


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
    if activity and activity.strip() not in _BORING_ACTIVITIES:
        # Cap at one unusual-activity notification per device per day — the
        # pipeline calls this once per segment, so without this guard a single
        # day could spawn many near-duplicate alerts.
        already = session.execute(
            select(func.count(Notification.id))
            .where(
                Notification.device == device,
                Notification.date == date,
                Notification.type == "unusual_activity",
            )
        ).scalar_one()
        if already:
            return

        cutoff = (
            datetime.strptime(date, "%Y-%m-%d") - timedelta(days=_ACTIVITY_LOOKBACK_DAYS)
        ).strftime("%Y-%m-%d")

        # Case-insensitive match so "Eating lunch" / "eating lunch" count as the
        # same activity and don't each look brand-new.
        recent_count = session.execute(
            select(func.count(Image.id))
            .where(
                Image.device == device,
                func.lower(func.trim(Image.activity)) == activity.strip().lower(),
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


# Synthetic segment_id per meal slot so the partial unique index
# uq_notif_with_segment (device, date, segment_id, type) yields exactly one
# late_meal notification per meal per day. Negative values never collide with
# real (positive) segment ids.
_MEAL_SLOT_ID = {"breakfast": -1, "lunch": -2, "dinner": -3}


def notify_late_meal(
    session: Session,
    device: str,
    date: str,
    meal: str,
    usual_minute: int,
) -> None:
    """Emit a 'late_meal' notification for the given meal slot (idempotent)."""
    hh, mm = divmod(usual_minute, 60)
    _upsert_notification(
        session,
        device=device,
        date=date,
        segment_id=_MEAL_SLOT_ID.get(meal),
        notif_type="late_meal",
        title=f"Late {meal}?",
        body=f"No meal detected yet — you usually have {meal} around {hh:02d}:{mm:02d}.",
        extra={"meal": meal, "usual_minute": usual_minute},
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

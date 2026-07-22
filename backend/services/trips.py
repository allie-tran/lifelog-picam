"""
Trip detection — group consecutive days spent away from home into trips.

A *trip* is a maximal run of consecutive days where the lifelogger was away from
any Home-labelled location (with a 1-day grace so a brief return doesn't split
one trip). Home is resolved from the device owner's `LocationLabel` rows
(label_kind='home') — reusing the labels the day/location layer already uses.

Public API:
    detect_trips(session, device, window_days) -> list[TripSpan]
    build_trip_summaries(session, device, window_days) -> list[PeriodSummary]
"""

import logging
from collections import Counter
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from database.models import Location, LocationLabel
from database.types import DaySummaryRecord
from schemas import DaySummary
from services.location_visits import _owner_username
from services.period_summary import build_period_summary

logger = logging.getLogger(__name__)

# A trip must span at least this many consecutive away-days.
_MIN_TRIP_DAYS = 2
# Allow a single home/blank day inside a trip without splitting it.
_GRACE_DAYS = 1


def _norm(s: str | None) -> str:
    return (s or "").strip().lower()


def _valid_date(s: str) -> bool:
    try:
        datetime.strptime(s, "%Y-%m-%d")
        return True
    except (ValueError, TypeError):
        return False


@dataclass
class TripSpan:
    start: str
    end: str
    days: int
    label: str          # primary destination (e.g. a city / top venue)


def home_location_ids(session: Session, device: str) -> set:
    """Location ids the device owner has labelled Home."""
    owner = _owner_username(device)
    if not owner:
        return set()
    rows = session.execute(
        select(LocationLabel.location_id)
        .where(LocationLabel.username == owner, LocationLabel.label_kind == "home")
    ).scalars().all()
    return set(rows)


def _home_names(session: Session, home_ids: set) -> set[str]:
    """Normalized names of the Home-labelled locations, for matching against a
    day's visit names (which store names, not ids)."""
    if not home_ids:
        return set()
    rows = session.execute(
        select(Location.name).where(Location.id.in_(home_ids))
    ).scalars().all()
    return {_norm(n) for n in rows if n} | {"home", "house"}


def detect_trips(session: Session, device: str, window_days: int | None = None) -> list[TripSpan]:
    """Return away-day trips. Scans ALL of the device's day summaries by default
    (so past trips surface); pass ``window_days`` to restrict to a trailing window."""
    date_filter: dict = {}
    if window_days is not None:
        end = datetime.now(timezone.utc).date()
        start = end - timedelta(days=window_days)
        date_filter = {"date": {"$gte": start.strftime("%Y-%m-%d"),
                                "$lte": end.strftime("%Y-%m-%d")}}
    recs = list(DaySummaryRecord.find(filter={"device": device, **date_filter}))
    recs = [r for r in recs if _valid_date(getattr(r, "date", ""))]
    if not recs:
        return []
    recs.sort(key=lambda r: r.date)
    days = [DaySummary.model_validate(r.__dict__) for r in recs]

    home_ids = home_location_ids(session, device)
    home_names = _home_names(session, home_ids)

    def is_away(day: DaySummary) -> bool | None:
        stops = [v for v in (day.location_visits or []) if v.location_stop is not False and v.location_name]
        if not stops:
            return None  # no location data — neutral (grace)
        return not any(_norm(v.location_name) in home_names for v in stops)

    # Walk calendar-adjacent days, grouping away-runs with a small grace.
    labeled = [(datetime.strptime(d.date, "%Y-%m-%d").date(), d, is_away(d)) for d in days]
    trips: list[TripSpan] = []
    i = 0
    n = len(labeled)
    while i < n:
        if labeled[i][2] is not True:
            i += 1
            continue
        # Start a run at the first away-day.
        j = i
        grace = 0
        run_days = []
        while j < n:
            date_j, day_j, away_j = labeled[j]
            # Break on a calendar gap larger than 1 day.
            if run_days and (date_j - labeled[j - 1][0]).days > 1:
                break
            if away_j is True:
                run_days.append((date_j, day_j))
                grace = 0
            elif away_j is None or away_j is False:
                if grace >= _GRACE_DAYS:
                    break
                grace += 1
            j += 1
        # Trim trailing grace days.
        if run_days:
            span_start = run_days[0][0]
            span_end = run_days[-1][0]
            if (span_end - span_start).days + 1 >= _MIN_TRIP_DAYS:
                label = _trip_label([d for _, d in run_days], home_names)
                trips.append(TripSpan(
                    start=span_start.strftime("%Y-%m-%d"),
                    end=span_end.strftime("%Y-%m-%d"),
                    days=len(run_days), label=label,
                ))
            i = j
        else:
            i += 1
    return trips


def _trip_label(days: list[DaySummary], home_names: set[str]) -> str:
    """Primary destination = the non-home place with the most time across the trip."""
    minutes: Counter = Counter()
    for day in days:
        for v in day.location_visits or []:
            name = (v.location_name or "").strip()
            if not name or v.location_stop is False or _norm(name) in home_names:
                continue
            minutes[name] += (v.duration or 0)
    if not minutes:
        return "Trip"
    top = minutes.most_common(1)[0][0]
    return f"Trip · {top}"


def build_trip_summaries(session: Session, device: str, window_days: int | None = 60):
    """Detect trips and build a period summary for each (kind='trip').

    Defaults to a trailing window so the nightly cron only (re)builds recent
    trips — older trips are listed by ``detect_trips`` and built lazily when a
    user opens them via /period-summary (then cached)."""
    out = []
    for t in detect_trips(session, device, window_days):
        try:
            out.append(build_period_summary(
                session, device, "trip", t.start, t.end, label=t.label
            ))
        except Exception as exc:
            logger.warning("build_trip_summaries failed for %s %s..%s: %s",
                           device, t.start, t.end, exc)
    return out

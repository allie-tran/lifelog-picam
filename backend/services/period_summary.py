"""
Multi-day period summaries — a hierarchy on top of the per-day DaySummary.

A *period* (week / month / trip / custom range) rolls up the DaySummary records
in its span. The day is the atomic unit; a period aggregates the days' metrics
and asks the LLM to summarize the days' *highlights* (not raw segments), which
keeps prompts small and gives real hierarchical abstraction.

Public API:
    aggregate_period(session, device, start, end)        -> PeriodSummary
    summarize_period_by_text(period, child_texts)        -> str
    build_period_summary(session, device, kind, s, e)    -> PeriodSummary  (persists)
    period_source_sig(day_records)                       -> str
"""

import hashlib
import logging
import math
from collections import defaultdict
from datetime import datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from database.models import BioDayStats
from database.types import DaySummaryRecord, PeriodSummaryRecord
from integrations.llm import llm
from schemas import BioTrend, BioTrendPoint, DaySummary, PeriodSummary, TopLocation, TrendItem

logger = logging.getLogger(__name__)

# Two visits count as the same place when their centroids fall within this
# radius (metres), even if the resolved names differ slightly. Mirrors the
# per-day merge radius in services/location_visits.py.
_LOC_MERGE_RADIUS_M = 200.0


def _haversine_m(lat1, lon1, lat2, lon2) -> float:
    """Great-circle distance in metres; inf when any coord missing."""
    if None in (lat1, lon1, lat2, lon2):
        return math.inf
    r = 6371000.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlmb = math.radians(lon2 - lon1)
    a = math.sin(dphi / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dlmb / 2) ** 2
    return 2 * r * math.asin(math.sqrt(a))


def _load_day_records(device: str, start: str, end: str) -> list[DaySummaryRecord]:
    """Day records in [start, end] (inclusive), ordered by date."""
    recs = list(DaySummaryRecord.find(
        filter={"device": device, "date": {"$gte": start, "$lte": end}}
    ))
    recs.sort(key=lambda r: r.date)
    return recs


def period_source_sig(day_records: list[DaySummaryRecord]) -> str:
    """Hash of the child days' identity+freshness, so a period can be reused
    from cache unless an underlying day actually changed."""
    parts = []
    for r in sorted(day_records, key=lambda x: x.date):
        gen = getattr(r, "text_summary_generated_at", None)
        parts.append(f"{r.date}|{gen.isoformat() if gen else ''}|{int(bool(getattr(r, 'updated', False)))}")
    return hashlib.sha1("\n".join(parts).encode()).hexdigest()


def _aggregate_top_locations(days: list[DaySummary]) -> list[TopLocation]:
    """Dedup location visits across the period's days into ranked places."""
    buckets: list[dict] = []
    for day in days:
        seen_names_today: set[str] = set()
        for v in day.location_visits or []:
            name = (v.location_name or "").strip()
            if not name or v.location_stop is False:  # skip transit/journeys
                continue
            key = name.lower()
            match = None
            for b in buckets:
                if b["key"] == key or _haversine_m(
                    b["lat"], b["lon"], v.location_latitude, v.location_longitude
                ) <= _LOC_MERGE_RADIUS_M:
                    match = b
                    break
            if match is None:
                match = {
                    "key": key, "name": name,
                    "lat": v.location_latitude, "lon": v.location_longitude,
                    "days": set(), "visits": 0, "minutes": 0.0,
                    "rep": v.representative_image,
                }
                buckets.append(match)
            match["visits"] += 1
            match["minutes"] += (v.duration or 0) / 60.0
            match["days"].add(day.date)
            if match["lat"] is None and v.location_latitude is not None:
                match["lat"], match["lon"] = v.location_latitude, v.location_longitude
            if match["rep"] is None and v.representative_image is not None:
                match["rep"] = v.representative_image
        seen_names_today.clear()
    out = [
        TopLocation(
            name=b["name"], latitude=b["lat"], longitude=b["lon"],
            days=len(b["days"]), visits=b["visits"],
            minutes=round(b["minutes"], 1), representative_image=b["rep"],
        )
        for b in buckets
    ]
    out.sort(key=lambda t: (t.minutes, t.visits), reverse=True)
    return out


def _aggregate_bio(session: Session, device: str, day_dates: list[str]) -> BioTrend | None:
    """Range-scan BioDayStats for the period; build series + averages."""
    if not day_dates:
        return None
    rows = session.execute(
        select(BioDayStats)
        .where(BioDayStats.device_id == device)
        .where(BioDayStats.date.in_(day_dates))
        .order_by(BioDayStats.date)
    ).scalars().all()
    if not rows:
        return None
    series = [
        BioTrendPoint(date=r.date, sleep_minutes=r.sleep_minutes,
                      avg_hr=r.avg_hr, step_count=r.step_count)
        for r in rows
    ]

    def _avg(vals):
        vals = [v for v in vals if v is not None]
        return round(sum(vals) / len(vals), 1) if vals else None

    return BioTrend(
        avg_sleep_minutes=_avg([r.sleep_minutes for r in rows]),
        avg_hr=_avg([r.avg_hr for r in rows]),
        resting_hr=_avg([r.resting_hr for r in rows]),
        max_hr=_avg([r.max_hr for r in rows]),
        avg_steps=_avg([r.step_count for r in rows]),
        series=series,
    )


def _default_label(kind: str, start: str, end: str) -> str:
    try:
        s = datetime.strptime(start, "%Y-%m-%d")
        e = datetime.strptime(end, "%Y-%m-%d")
    except ValueError:
        return f"{start} – {end}"
    if kind == "week":
        return f"Week of {s.strftime('%b %-d, %Y')}"
    if kind == "month":
        return s.strftime("%B %Y")
    if s.date() == e.date():
        return s.strftime("%b %-d, %Y")
    if (s.year, s.month) == (e.year, e.month):
        return f"{s.strftime('%b %-d')}–{e.strftime('%-d, %Y')}"
    return f"{s.strftime('%b %-d')} – {e.strftime('%b %-d, %Y')}"


def aggregate_period(session: Session, device: str, start: str, end: str,
                     kind: str = "custom", label: str | None = None) -> PeriodSummary:
    """Roll up the DaySummary records in [start, end] into a PeriodSummary
    (without the LLM narrative or trends — those are added by build_period_summary)."""
    recs = _load_day_records(device, start, end)
    days = [DaySummary.model_validate(r.__dict__) for r in recs]

    category_minutes: dict[str, float] = defaultdict(float)
    binary_totals: dict[str, float] = defaultdict(float)
    burst_totals: dict[str, int] = defaultdict(int)
    total_minutes = 0.0
    total_images = 0
    day_dates: list[str] = []
    active_days = 0

    for day in days:
        day_dates.append(day.date)
        if (day.total_minutes or 0) > 0 or day.segments:
            active_days += 1
        total_minutes += day.total_minutes or 0.0
        total_images += day.total_images or 0
        for cat, mins in (day.category_minutes or {}).items():
            category_minutes[cat] += mins
        for name, val in (day.binary_metrics or {}).items():
            binary_totals[name] += val
        for name, stamps in (day.burst_metrics or {}).items():
            burst_totals[name] += len(stamps or [])

    return PeriodSummary(
        kind=kind, device=device, start_date=start, end_date=end,
        label=label or _default_label(kind, start, end),
        day_dates=day_dates, active_days=active_days,
        child_kind="day", child_keys=day_dates,
        category_minutes={k: round(v, 1) for k, v in category_minutes.items()},
        total_minutes=round(total_minutes, 1), total_images=total_images,
        binary_totals={k: round(v, 1) for k, v in binary_totals.items()},
        burst_totals=dict(burst_totals),
        top_locations=_aggregate_top_locations(days),
        bio_trend=_aggregate_bio(session, device, day_dates),
        source_sig=period_source_sig(recs),
    )


def summarize_period_by_text(period: PeriodSummary, child_texts: list[str]) -> str:
    """LLM recap of the whole period from its days' highlights. Reuses the
    routine-skipping, markdown highlights style of the per-day summary."""
    notes = [t.strip() for t in child_texts if (t or "").strip()]
    if not notes:
        return ""
    span = f"{period.label} ({len(period.day_dates)} days)"
    places = ", ".join(t.name for t in period.top_locations[:6])
    try:
        return str(llm.generate_from_text(
            f"Below are the per-day highlight notes for a lifelogger's {period.kind} "
            f"— {span}. Each block is one day.\n\n"
            "Write a recap of the WHOLE period as Markdown, in two parts:\n"
            "1. A short narrative (3-5 sentences) capturing the shape of the "
            "period — the main places and how the days went overall.\n"
            "2. A '**Highlights**' line, then 3-6 Markdown bullets ('- ') for the "
            "most notable, memorable, or unusual moments ACROSS the whole period.\n\n"
            "SKIP everyday routine that recurs on most days (grooming, commuting, "
            "checking the phone, generic 'having food'/'coffee'). Mention a meal only "
            "when the specific dish or venue is distinctive. Prefer moments that stood "
            "out over the span. Ground every detail in the notes — do NOT invent. "
            "Address the person as 'you'. No top-level title.\n\n"
            f"Main places this period: {places}\n\n"
            + "\n\n".join(notes)
        )).strip()
    except Exception as exc:
        logger.warning("summarize_period_by_text failed: %s", exc)
        return ""


def _extract_highlights(summary_text: str) -> list[str]:
    """Pull the bullet lines out of the markdown summary for structured display."""
    out = []
    for line in (summary_text or "").splitlines():
        s = line.strip()
        if s.startswith(("- ", "* ")):
            out.append(s[2:].strip())
    return out


# Only surface a category/bio change as a trend when it moves by at least this
# fraction vs the previous period — filters out noise.
_TREND_MIN_FRAC = 0.15
_MINUTES_FLOOR = 20.0  # ignore categories under ~20 min in both periods


def _shift_range(start: str, end: str) -> tuple[str, str]:
    """The equal-length window immediately before [start, end]."""
    s = datetime.strptime(start, "%Y-%m-%d")
    e = datetime.strptime(end, "%Y-%m-%d")
    span = (e - s).days + 1
    prev_end = s - timedelta(days=1)
    prev_start = prev_end - timedelta(days=span - 1)
    return prev_start.strftime("%Y-%m-%d"), prev_end.strftime("%Y-%m-%d")


def _pct_note(label: str, cur: float, prev: float, unit: str = "min") -> str:
    if prev <= 0:
        return f"{label}: new this period ({cur:.0f} {unit})"
    pct = round((cur - prev) / prev * 100)
    arrow = "up" if cur > prev else "down"
    return f"{label} {arrow} {abs(pct)}% ({prev:.0f}→{cur:.0f} {unit})"


def compute_trends(session: Session, current: PeriodSummary) -> list[TrendItem]:
    """Period-over-period behavioural changes vs the equal-length previous window:
    category-minute shifts, bio deltas, and new/dropped places."""
    prev_start, prev_end = _shift_range(current.start_date, current.end_date)
    prev = aggregate_period(session, current.device, prev_start, prev_end, kind=current.kind)
    trends: list[TrendItem] = []

    # Category-minute shifts
    cats = set(current.category_minutes) | set(prev.category_minutes)
    for cat in cats:
        cur = current.category_minutes.get(cat, 0.0)
        pv = prev.category_minutes.get(cat, 0.0)
        if cur < _MINUTES_FLOOR and pv < _MINUTES_FLOOR:
            continue
        base = max(pv, 1.0)
        if abs(cur - pv) / base < _TREND_MIN_FRAC:
            continue
        direction = "new" if pv == 0 else ("gone" if cur == 0 else ("up" if cur > pv else "down"))
        trends.append(TrendItem(
            metric=cat, current=round(cur, 1), previous=round(pv, 1),
            delta=round(cur - pv, 1), direction=direction,
            note=_pct_note(cat, cur, pv),
        ))

    # Bio deltas
    cbio, pbio = current.bio_trend, prev.bio_trend
    if cbio and pbio:
        for attr, label, unit in (
            ("avg_sleep_minutes", "Sleep", "min"),
            ("avg_steps", "Steps", ""),
            ("resting_hr", "Resting HR", "bpm"),
        ):
            cur = getattr(cbio, attr, None)
            pv = getattr(pbio, attr, None)
            if cur is None or pv is None or pv == 0:
                continue
            if abs(cur - pv) / pv < _TREND_MIN_FRAC:
                continue
            trends.append(TrendItem(
                metric=label, current=round(cur, 1), previous=round(pv, 1),
                delta=round(cur - pv, 1), direction=("up" if cur > pv else "down"),
                note=_pct_note(label, cur, pv, unit).strip(),
            ))

    # New vs dropped places
    cur_places = {t.name for t in current.top_locations}
    prev_places = {t.name for t in prev.top_locations}
    for name in list(cur_places - prev_places)[:5]:
        trends.append(TrendItem(metric=name, direction="new", note=f"New place: {name}"))

    # Rank: biggest relative movers first, "new place" last.
    trends.sort(key=lambda t: abs(t.delta or 0), reverse=True)
    return trends[:12]


def build_period_summary(session: Session, device: str, kind: str,
                         start: str, end: str, label: str | None = None) -> PeriodSummary:
    """Aggregate → summarize → persist. Reuses the cached record when the child
    days are unchanged (source_sig match)."""
    recs = _load_day_records(device, start, end)
    sig = period_source_sig(recs)
    existing = PeriodSummaryRecord.find_one(filter={
        "device": device, "kind": kind, "start_date": start, "end_date": end,
    })
    if existing and existing.source_sig == sig and existing.summary_text and not existing.updated:
        return PeriodSummary.model_validate(existing.__dict__)

    period = aggregate_period(session, device, start, end, kind=kind, label=label)
    child_texts = [r.summary_text for r in recs if getattr(r, "summary_text", "")]
    period.summary_text = summarize_period_by_text(period, child_texts)
    period.highlights = _extract_highlights(period.summary_text)
    try:
        period.trends = compute_trends(session, period)
    except Exception as exc:
        logger.warning("compute_trends failed for %s %s..%s: %s", device, start, end, exc)
    period.generated_at = datetime.now(timezone.utc)
    period.processing = False
    period.updated = False

    PeriodSummaryRecord.update_one(
        {"device": device, "kind": kind, "start_date": start, "end_date": end},
        data={"$set": period.model_dump()},
        upsert=True,
    )
    return period


def _period_summary_bg(device: str, kind: str, start: str, end: str) -> None:
    """Background entry point: opens its own session, builds+persists the period.
    Clears the `processing` flag on failure so the record isn't stuck."""
    from database import SessionLocal
    session = SessionLocal()
    try:
        build_period_summary(session, device, kind, start, end)
    except Exception as exc:
        logger.error("_period_summary_bg failed for %s/%s %s..%s: %s",
                     device, kind, start, end, exc)
        PeriodSummaryRecord.update_one(
            {"device": device, "kind": kind, "start_date": start, "end_date": end},
            data={"$set": {"processing": False}},
            upsert=True,
        )
    finally:
        session.close()

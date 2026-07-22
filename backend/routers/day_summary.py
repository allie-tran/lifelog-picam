"""Day-summary, date (re)processing, goal targets and segment-activity endpoints.

Mounted on the root app without a prefix so the original paths
(``/day-summary``, ``/process-date``, ``/resync-day``, ``/get-targets``,
``/update-targets``, ``/change-segment-activity``) are unchanged.
"""
import logging
from datetime import datetime, timezone
from typing import Annotated, List, Optional

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException
from sqlalchemy import func, select, update
from sqlalchemy.orm import Session

from auth import _require_any_access, _require_owner
from auth.auth_models import auth_dependency, get_user
from auth.types import AccessLevel, User
from core.dependencies import CamelCaseModel
from database import get_session
from database.models import Image as ImageModel
from database.types import DaySummaryRecord, ImageRecord, PeriodSummaryRecord
from schemas import CustomTarget, DaySummary, PeriodSummary
from services.summary import summarize_lifelog_by_day, update_dirty_segments
from tasks import describe_segment_task
from tasks.day_summary import (
    DEFAULT_TARGETS,
    _LIVE_THRESHOLD_MINUTES,
    _day_summary_bg,
    _get_last_n_summaries,
    _process_date_bg,
    _text_summary_bg,
)

logger = logging.getLogger(__name__)

router = APIRouter()


class ChangeSegmentActivityRequest(CamelCaseModel):
    date: str
    segment_id: int
    new_activity_info: str


# ---------------------------------------------------------------------------
# Segment processing
# ---------------------------------------------------------------------------

@router.post("/resync-day", summary="Re-segment a day from the first gap")
def resync_day(
    date: str,
    device: str,
    access_level: Annotated[AccessLevel, Depends(auth_dependency)] = AccessLevel.NONE,
):
    """Re-segment from first gap, skip LLM for already-annotated segments."""
    _require_owner(access_level)
    from tasks import resync_day_task
    # Bust caches synchronously here too: the task busts them when it finishes, but
    # doing it now means a stale day-nav/browse cache can't be served while the
    # worker is still running (or lagging behind a code change).
    from integrations.sessions.redis import bust_day_caches
    bust_day_caches(device, date)
    resync_day_task.delay(device, date)
    return {"message": f"Resync queued for {device}/{date}"}


@router.get("/process-date", summary="Segment/annotate a date in the background")
def process_date(
    date: str,
    device: str,
    background_tasks: BackgroundTasks,
    resegment: bool = False,
    reannotate: bool = False,
    access_level: Annotated[AccessLevel, Depends(auth_dependency)] = AccessLevel.NONE,
    session: Session = Depends(get_session),
):
    """Kick off (re)segmentation and activity annotation for a date.

    With ``resegment``/``reannotate`` the existing segment + activity fields are
    cleared first. Returns immediately; work runs in a background task.
    """
    _require_any_access(access_level)

    if not resegment and not reannotate:
        existing = DaySummaryRecord.find_one(filter={"date": date, "device": device})
        if existing and getattr(existing, "processing", False):
            return {"message": "Already processing.", "processing": True}

    if resegment or reannotate:
        session.execute(
            update(ImageModel)
            .where(ImageModel.date == date)
            .where(ImageModel.deleted == False)
            .where(ImageModel.device == device)
            .values(
                activity="",
                activity_description="",
                activity_confidence="",
                segment_id=None,
            )
        )
        session.commit()
        session.flush()
        logger.info("Reset segments for date %s and device %s.", date, device)

    DaySummaryRecord.update_one(
        {"date": date, "device": device},
        data={"$set": {"processing": True, "segments": [], "summary_text": "", "dirty_segment_ids": [], "text_summary_stale": True}},
        upsert=True,
    )
    background_tasks.add_task(_process_date_bg, device, date, reannotate)
    return {"message": f"Processing segments for date {date} in background.", "processing": True}


# ---------------------------------------------------------------------------
# Day summary
# ---------------------------------------------------------------------------

@router.get("/day-summary", response_model=Optional[DaySummary],
            summary="Get (or trigger generation of) a day's summary")
def get_day_summary(
    date: str,
    device: str,
    background_tasks: BackgroundTasks,
    user=Depends(get_user),
    access_level: Annotated[AccessLevel, Depends(auth_dependency)] = AccessLevel.NONE,
    session: Session = Depends(get_session),
):
    """Return the cached day summary, or dispatch background generation.

    Serves a cache hit when the stored summary is fresh; otherwise returns a
    partial/placeholder summary and schedules a full rebuild, incremental patch,
    or LLM text refresh as needed. ``None`` when the day has no images.
    """
    _require_any_access(access_level)

    if not date:
        raise HTTPException(status_code=400, detail="Date is required.")

    number_of_images = session.execute(
        select(func.count(ImageModel.id)).where(
            ImageModel.date == date,
            ImageModel.device == device,
            ImageModel.deleted == False,
        )
    ).scalar_one()

    if number_of_images == 0:
        return None

    last_image = session.execute(
        select(ImageModel).where(
            ImageModel.date == date,
            ImageModel.device == device,
            ImageModel.deleted == False,
        ).order_by(ImageModel.image_path.desc())
    ).scalars().first()
    last_image_time = last_image.timestamp if last_image else None

    today = datetime.now().strftime("%Y-%m-%d")
    is_live = False
    if date == today and last_image_time is not None:
        ts = last_image_time.replace(tzinfo=timezone.utc) if last_image_time.tzinfo is None else last_image_time
        age = (datetime.now(timezone.utc) - ts).total_seconds() / 60
        is_live = age < _LIVE_THRESHOLD_MINUTES

    day_summary = DaySummaryRecord.find_one(filter={"date": date, "device": device})

    if (
        day_summary
        and day_summary.segments
        and not getattr(day_summary, "updated", False)
        and not getattr(day_summary, "dirty_segment_ids", [])
        and not getattr(day_summary, "text_summary_stale", False)
        and not getattr(day_summary, "processing", False)
        and (is_live or (
            day_summary.number_of_images == number_of_images
            and day_summary.last_image_time == last_image_time
        ))
    ):
        logger.info("day-summary cache hit for %s/%s", device, date)
        cached = DaySummary.model_validate(day_summary.__dict__)
        cached.is_live = is_live
        return cached

    if getattr(day_summary, "processing", False):
        logger.info("day-summary: background task already running for %s/%s", device, date)
        if day_summary and day_summary.segments:
            partial = DaySummary.model_validate(day_summary.__dict__)
        else:
            partial = DaySummary(device=device, date=date, segments=[], summary_text="")
        partial.processing = True
        partial.is_live = is_live
        partial.number_of_images = number_of_images
        partial.last_image_time = last_image_time  # type: ignore
        return partial

    dirty_ids: list[int] = list(getattr(day_summary, "dirty_segment_ids", []) or [])
    text_stale: bool = bool(getattr(day_summary, "text_summary_stale", True))

    need_full_rebuild = (
        day_summary is None
        or not day_summary.segments
        or (not is_live and day_summary.number_of_images != number_of_images)
    )

    if need_full_rebuild:
        logger.info("Full day-summary rebuild (background) for %s/%s", device, date)
        my_targets = user.goal_targets or DEFAULT_TARGETS
        target_dicts = [{"name": t.name, "action_type": t.action_type.value, "query_prompt": t.query_prompt} for t in my_targets]
        DaySummaryRecord.update_one(
            {"date": date, "device": device},
            data={"$set": {"processing": True, "date": date, "device": device}},
            upsert=True,
        )
        background_tasks.add_task(_day_summary_bg, device, date, target_dicts)
        return DaySummary(
            device=device, date=date, segments=[],
            summary_text="", processing=True, is_live=is_live,
            number_of_images=number_of_images, last_image_time=last_image_time,  # type: ignore
        )

    if dirty_ids:
        logger.info(
            "Incremental segment patch for %s/%s (dirty: %s)",
            device, date, dirty_ids,
        )
        summary = DaySummary.model_validate(day_summary.__dict__)
        summary.segments = update_dirty_segments(
            session, device, date, dirty_ids, summary.segments
        )
        summary.dirty_segment_ids = []
    else:
        summary = DaySummary.model_validate(day_summary.__dict__)

    # Determine if LLM text needs regeneration.
    # For live days: throttle to at most once per hour.
    _last_text_gen = getattr(day_summary, "text_summary_generated_at", None)
    if _last_text_gen and _last_text_gen.tzinfo is None:
        _last_text_gen = _last_text_gen.replace(tzinfo=timezone.utc)
    _text_age_hours = (
        (datetime.now(timezone.utc) - _last_text_gen).total_seconds() / 3600
        if _last_text_gen else float("inf")
    )
    needs_text_regen = text_stale or (is_live and _text_age_hours >= 1.0)

    if needs_text_regen:
        reason = "stale" if text_stale else "hourly live refresh"
        logger.info("Text summary (%s) for %s/%s — dispatching background LLM task", reason, device, date)
        summary.processing = True
        DaySummaryRecord.update_one(
            {"date": date, "device": device},
            data={"$set": {**summary.model_dump(), "dirty_segment_ids": [], "processing": True}},
            upsert=True,
        )
        background_tasks.add_task(_text_summary_bg, device, date, is_live)
        summary.is_live = is_live
        summary.number_of_images = number_of_images
        summary.last_image_time = last_image_time  # type: ignore
        return summary

    my_targets = user.goal_targets or DEFAULT_TARGETS
    summary = summarize_lifelog_by_day(session, summary, my_targets)

    from database.models import BioDayStats as BioDayStatsModel
    bio = session.execute(
        select(BioDayStatsModel).where(
            BioDayStatsModel.device_id == device,
            BioDayStatsModel.date == date,
        )
    ).scalars().first()
    if bio:
        summary.avg_hr = bio.avg_hr
        summary.resting_hr = bio.resting_hr
        summary.max_hr = bio.max_hr
        summary.rmssd = bio.rmssd
        summary.step_count = bio.step_count
        summary.sleep_start = bio.sleep_start  # type: ignore
        summary.sleep_end = bio.sleep_end  # type: ignore
        summary.sleep_minutes = bio.sleep_minutes

    summary.number_of_images = number_of_images
    summary.last_image_time = last_image_time  # type: ignore
    summary.is_live = is_live
    summary.dirty_segment_ids = []
    summary.updated = False
    summary.processing = False

    DaySummaryRecord.update_one(
        {"date": date, "device": device},
        data={"$set": {**summary.model_dump(), "dirty_segment_ids": [], "text_summary_stale": False, "processing": False}},
        upsert=True,
    )

    return summary


# ---------------------------------------------------------------------------
# Multi-day period summary (week / month / trip / custom)
# ---------------------------------------------------------------------------

_PERIOD_KINDS = {"week", "month", "trip", "custom"}


@router.get("/period-summary", response_model=Optional[PeriodSummary],
            summary="Get (or trigger generation of) a multi-day period summary")
def get_period_summary(
    device: str,
    start: str,
    end: str,
    background_tasks: BackgroundTasks,
    kind: str = "custom",
    access_level: Annotated[AccessLevel, Depends(auth_dependency)] = AccessLevel.NONE,
    session: Session = Depends(get_session),
):
    """Roll up the day summaries in [start, end] into a period summary.

    Serves a cache hit when the underlying days are unchanged (``source_sig``);
    otherwise schedules a background build and returns a ``processing``
    placeholder. ``None`` when the range has no summarized days.
    """
    _require_any_access(access_level)
    if kind not in _PERIOD_KINDS:
        raise HTTPException(status_code=400, detail=f"kind must be one of {sorted(_PERIOD_KINDS)}")
    if not start or not end or start > end:
        raise HTTPException(status_code=400, detail="Valid start and end (start<=end) required.")

    from services.period_summary import (
        _load_day_records, _period_summary_bg, aggregate_period, period_source_sig,
    )

    recs = _load_day_records(device, start, end)
    if not recs:
        return None
    sig = period_source_sig(recs)

    existing = PeriodSummaryRecord.find_one(filter={
        "device": device, "kind": kind, "start_date": start, "end_date": end,
    })

    if (
        existing and existing.summary_text
        and existing.source_sig == sig
        and not getattr(existing, "updated", False)
        and not getattr(existing, "processing", False)
    ):
        logger.info("period-summary cache hit for %s/%s %s..%s", device, kind, start, end)
        return PeriodSummary.model_validate(existing.__dict__)

    if getattr(existing, "processing", False):
        return PeriodSummary.model_validate(existing.__dict__)

    # Schedule a background build; return the aggregated shell (metrics + top
    # locations are cheap and useful immediately) with processing=True.
    shell = aggregate_period(session, device, start, end, kind=kind)
    shell.processing = True
    PeriodSummaryRecord.update_one(
        {"device": device, "kind": kind, "start_date": start, "end_date": end},
        data={"$set": {**shell.model_dump(), "processing": True}},
        upsert=True,
    )
    background_tasks.add_task(_period_summary_bg, device, kind, start, end)
    return shell


class TripSpanResponse(CamelCaseModel):
    start: str
    end: str
    days: int
    label: str


@router.get("/trips", response_model=List[TripSpanResponse],
            summary="Detected multi-day trips (away from home) for the picker")
def get_trips(
    device: str,
    window_days: Optional[int] = None,
    access_level: Annotated[AccessLevel, Depends(auth_dependency)] = AccessLevel.NONE,
    session: Session = Depends(get_session),
):
    """Lightweight trip detection (no LLM) — spans + destination labels over the
    device's FULL history by default (pass ``window_days`` to restrict). Selecting
    one fetches its full summary via /period-summary?kind=trip (built lazily)."""
    _require_any_access(access_level)
    from services.trips import detect_trips
    spans = detect_trips(session, device, window_days=window_days)
    # Most recent trips first for the picker.
    spans.sort(key=lambda t: t.start, reverse=True)
    return [TripSpanResponse(start=t.start, end=t.end, days=t.days, label=t.label) for t in spans]


# ---------------------------------------------------------------------------
# Targets
# ---------------------------------------------------------------------------

@router.get("/get-targets", summary="Get the user's goal targets")
def get_targets(
    user=Depends(get_user),
    access_level: Annotated[AccessLevel, Depends(auth_dependency)] = AccessLevel.NONE,
):
    _require_any_access(access_level)
    return user.goal_targets or DEFAULT_TARGETS


@router.post("/update-targets", summary="Replace the user's goal targets")
def update_targets(
    targets: List[CustomTarget],
    user=Depends(get_user),
    access_level: Annotated[AccessLevel, Depends(auth_dependency)] = AccessLevel.NONE,
):
    _require_owner(access_level)
    targets = targets or DEFAULT_TARGETS
    user.goal_targets = targets
    User.update_one({"username": user.username}, {"$set": {"goal_targets": targets}})
    return {"message": "Targets updated successfully."}


# ---------------------------------------------------------------------------
# Segment activity
# ---------------------------------------------------------------------------

@router.post("/change-segment-activity", summary="Re-describe a segment with user-supplied activity info")
async def change_segment_activity(
    request: ChangeSegmentActivityRequest,
    device: str,
    access_level: Annotated[AccessLevel, Depends(auth_dependency)] = AccessLevel.NONE,
    session: Session = Depends(get_session),
):
    _require_owner(access_level)

    segment = ImageRecord.find_one(
        session, segment_id=request.segment_id, device=device, date=request.date
    )
    if not segment or segment.segment_id is None:
        raise HTTPException(status_code=404, detail="Segment not found")

    all_summaries = _get_last_n_summaries(
        session, segment.date, device, n=10, segment_id_lt=request.segment_id
    )

    thumbnails = [
        img.thumbnail
        for img in ImageRecord.find(
            session,
            segment_id=segment.segment_id,
            date=request.date,
            deleted=False,
            device=device,
            sort="image_path",
            sort_desc=False,
        )
    ]

    describe_segment_task.delay(
        device,
        request.date,
        thumbnails,
        segment.segment_id,
        extra_info=[
            f"The previous activity descriptions were: {', '.join(all_summaries)}.",
            f"Here is the provided activity information from the camera viewer: {request.new_activity_info}. Incorporate this into the description.",
        ],
    )

    DaySummaryRecord.update_one(
        {
            "date": request.date,
            "device": device,
        },
        data={"$set": {"updated": True}},
    )

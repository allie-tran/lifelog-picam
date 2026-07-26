"""Background task functions and helpers for day-summary processing."""

import hashlib
import logging
from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import desc, func, select, update
from sqlalchemy.orm import Session
from tqdm.auto import tqdm

from schemas import ActionType, CustomTarget, DaySummary
from database import engine as _db_engine
from database.models import Image as ImageModel
from database.types import DaySummaryRecord, ImageRecord
from services.segmentation import load_all_segments
from services.summary import (
    create_day_timeline,
    summarize_day_by_text,
    summarize_lifelog_by_day,
    update_dirty_segments,
)
from tasks import describe_segment_task

logger = logging.getLogger(__name__)

_LIVE_THRESHOLD_MINUTES = 20  # day is "live" if last image arrived within this window

DEFAULT_TARGETS = [
    CustomTarget(
        "Phone",
        ActionType.BURST,
        "checking or using a phone (e.g., texting, calling, browsing)",
    ),
    CustomTarget(
        "Computer",
        ActionType.BINARY,
        "using a computer (e.g., typing, video calls, browsing)",
    ),
    CustomTarget("Eating", ActionType.PERIOD, "a photo of a meal on a table"),
]


def _get_last_n_summaries(
    session: Session,
    date: str,
    device: str,
    n: int = 10,
    segment_id_lt: Optional[int] = None,
) -> list[str]:
    stmt = (
        select(ImageModel.segment_id, ImageModel.activity_description)
        .where(ImageModel.date == date)
        .where(ImageModel.deleted == False)
        .where(ImageModel.activity != "")
        .where(ImageModel.device == device)
        .distinct(ImageModel.segment_id)
        .order_by(desc(ImageModel.segment_id))
        .limit(n)
    )
    if segment_id_lt is not None:
        stmt = stmt.where(ImageModel.segment_id < segment_id_lt)
    rows = session.execute(stmt).fetchall()
    return [row.activity_description for row in reversed(rows)]


def _segments_signature(segments) -> str:
    """Stable hash of the segment fields that drive location-visit grouping
    (id, place, time span). Equal signature ⇒ identical visits, so the expensive
    LLM/web-search rebuild can be skipped and the stored visits reused."""
    parts = [
        f"{s.segment_id}|{s.location_name}|{s.start_time.isoformat()}|{s.end_time.isoformat()}"
        for s in sorted(segments, key=lambda x: (x.start_time, x.segment_id or 0))
    ]
    return hashlib.sha1("\n".join(parts).encode()).hexdigest()


def _resolve_location_visits(session, device: str, date: str, segments, existing):
    """Build location visits, or reuse the stored ones when the segment signature
    is unchanged since they were built (segments haven't *actually* changed — e.g.
    a late GPS upload that reclustered nothing, or a text-only refresh). Returns
    ``(visits, signature)``."""
    sig = _segments_signature(segments)
    if (
        existing is not None
        and getattr(existing, "location_visits_sig", None) == sig
        and getattr(existing, "location_visits", None)
    ):
        logger.info("location visits unchanged for %s/%s — reusing (sig %s)", device, date, sig[:8])
        return list(existing.location_visits), sig
    from services.location_visits import build_location_visits
    return build_location_visits(session, device, date, segments), sig


def _day_summary_bg(device: str, date: str, target_dicts: list) -> None:
    """Background: full day-summary rebuild (segmentation → timeline → LLM → CLIP)."""
    from sqlalchemy.orm import Session as _Session
    try:
        with _Session(_db_engine) as session:
            load_all_segments(session, device, date, skip_annotations=False)
            segments = create_day_timeline(session, device, date)
            if not segments:
                logger.warning("_day_summary_bg: no segments found for %s/%s", device, date)
                DaySummaryRecord.update_one(
                    {"date": date, "device": device},
                    data={"$set": {"processing": False}},
                    upsert=True,
                )
                return

            targets = [CustomTarget(name=t["name"], action_type=ActionType(t["action_type"]), query_prompt=t["query_prompt"]) for t in target_dicts]
            summary = DaySummary(
                device=device, date=date, segments=segments,
                summary_text="", updated=False, dirty_segment_ids=[], text_summary_stale=False,
            )

            last_img_ts = segments[-1].end_time if segments else None
            _today = datetime.now().strftime("%Y-%m-%d")
            _is_live = False
            if date == _today and last_img_ts is not None:
                _ts = last_img_ts.replace(tzinfo=timezone.utc) if last_img_ts.tzinfo is None else last_img_ts
                _is_live = (datetime.now(timezone.utc) - _ts).total_seconds() / 60 < _LIVE_THRESHOLD_MINUTES

            # Prior record (if any) — used to reuse location visits when the
            # segments are unchanged, so we don't re-run the LLM/web-search.
            _prev = DaySummaryRecord.find_one(filter={"date": date, "device": device})
            _existing = DaySummary.model_validate(_prev.__dict__) if _prev else None

            # Location-visit descriptions: one specific summary per place visited.
            # Built for every day incl. the live one (no live gate); the signature
            # reuse below keeps repeated builds cheap when nothing changed.
            try:
                summary.location_visits, summary.location_visits_sig = _resolve_location_visits(
                    session, device, date, segments, _existing
                )
            except Exception as _lve:
                logger.warning("_day_summary_bg: location visits failed for %s/%s: %s", device, date, _lve)

            summary = summarize_day_by_text(session, summary)
            summary.text_summary_stale = False
            summary.text_summary_generated_at = datetime.now(timezone.utc)

            if not _is_live:
                try:
                    from services.novelty import generate_unique_day_highlight
                    from services.notify import notify_day_complete, notify_novelty
                    highlight, novel_ids = generate_unique_day_highlight(session, device, date)
                    summary.unique_highlight = highlight
                    summary.novelty_segments = novel_ids
                    notify_day_complete(session, device, date, summary.summary_text)
                    if highlight:
                        rep_thumb = None
                        if novel_ids:
                            _rep = session.execute(
                                select(ImageModel.thumbnail)
                                .where(
                                    ImageModel.device == device,
                                    ImageModel.segment_id == novel_ids[0],
                                    ImageModel.date == date,
                                    ImageModel.deleted == False,
                                )
                                .limit(1)
                            ).scalars().first()
                            rep_thumb = _rep
                        notify_novelty(session, device, date, highlight, rep_thumb)
                    session.commit()
                except Exception as _nve:
                    logger.warning("_day_summary_bg: novelty step failed for %s/%s: %s", device, date, _nve)

            summary = summarize_lifelog_by_day(session, summary, targets)

            # Eating focus: dispatch one food pass per meal that lacks a record.
            try:
                from tasks import enqueue_meal_food
                enqueue_meal_food(session, device, date, list(summary.segments))
            except Exception as _fe:
                logger.warning("_day_summary_bg: meal food dispatch failed for %s/%s: %s", device, date, _fe)

            from database.models import BioDayStats as _BioDayStats
            bio = session.execute(
                select(_BioDayStats).where(_BioDayStats.device_id == device, _BioDayStats.date == date)
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

            n = session.execute(
                select(func.count(ImageModel.id)).where(
                    ImageModel.date == date, ImageModel.device == device, ImageModel.deleted == False,
                )
            ).scalar_one()
            last_img = session.execute(
                select(ImageModel).where(
                    ImageModel.date == date, ImageModel.device == device, ImageModel.deleted == False,
                ).order_by(ImageModel.image_path.desc())
            ).scalars().first()

            summary.number_of_images = n
            summary.last_image_time = last_img.timestamp if last_img else None  # type: ignore
            summary.dirty_segment_ids = []
            summary.updated = False
            summary.processing = False

            DaySummaryRecord.update_one(
                {"date": date, "device": device},
                data={"$set": {**summary.model_dump(), "dirty_segment_ids": [], "text_summary_stale": False, "processing": False}},
                upsert=True,
            )
            logger.info("_day_summary_bg complete for %s/%s", device, date)
    except Exception as exc:
        logger.error("_day_summary_bg failed for %s/%s: %s", device, date, exc)
        DaySummaryRecord.update_one(
            {"date": date, "device": device},
            data={"$set": {"processing": False}},
            upsert=True,
        )


def _text_summary_bg(device: str, date: str, is_live: bool = False) -> None:
    """Background: regenerate only the LLM text summary for an existing day record."""
    from sqlalchemy.orm import Session as _Session
    try:
        with _Session(_db_engine) as session:
            existing = DaySummaryRecord.find_one(filter={"date": date, "device": device})
            if not existing or not existing.segments:
                return
            summary = DaySummary.model_validate(existing.__dict__)
            if summary.segments:
                try:
                    # Reuse stored visits when segments are unchanged; the live gate
                    # no longer suppresses them, so the current day gets visits too.
                    summary.location_visits, summary.location_visits_sig = _resolve_location_visits(
                        session, device, date, summary.segments, summary
                    )
                except Exception as _lve:
                    logger.warning("_text_summary_bg: location visits failed for %s/%s: %s", device, date, _lve)
            # Eating focus: on a live/incremental day this is the path that runs,
            # so dispatch the per-meal food pass for any NEW meal here (not only in
            # the full rebuild), then attach whatever food is already stored.
            try:
                from tasks import enqueue_meal_food
                enqueue_meal_food(session, device, date, list(summary.segments))
            except Exception as _me:
                logger.warning("_text_summary_bg: meal food dispatch failed for %s/%s: %s", device, date, _me)
            try:
                from services.summary import attach_food_to_summary
                attach_food_to_summary(session, summary)
            except Exception as _fe:
                logger.warning("_text_summary_bg: food attach failed for %s/%s: %s", device, date, _fe)
            summary = summarize_day_by_text(session, summary)
            summary.text_summary_stale = False
            summary.text_summary_generated_at = datetime.now(timezone.utc)
            if not is_live:
                try:
                    from services.novelty import generate_unique_day_highlight
                    from services.notify import notify_day_complete, notify_novelty
                    highlight, novel_ids = generate_unique_day_highlight(session, device, date)
                    summary.unique_highlight = highlight
                    summary.novelty_segments = novel_ids
                    notify_day_complete(session, device, date, summary.summary_text)
                    if highlight:
                        rep_thumb = None
                        if novel_ids:
                            _rep = session.execute(
                                select(ImageModel.thumbnail)
                                .where(
                                    ImageModel.device == device,
                                    ImageModel.segment_id == novel_ids[0],
                                    ImageModel.date == date,
                                    ImageModel.deleted == False,
                                )
                                .limit(1)
                            ).scalars().first()
                            rep_thumb = _rep
                        notify_novelty(session, device, date, highlight, rep_thumb)
                    session.commit()
                except Exception as _nve:
                    logger.warning("_text_summary_bg: novelty step failed for %s/%s: %s", device, date, _nve)
            DaySummaryRecord.update_one(
                {"date": date, "device": device},
                data={"$set": {
                    "summary_text": summary.summary_text,
                    "location_visits": [v.model_dump() for v in summary.location_visits],
                    "location_visits_sig": summary.location_visits_sig,
                    "text_summary_stale": False,
                    "text_summary_generated_at": summary.text_summary_generated_at,
                    "unique_highlight": summary.unique_highlight,
                    "novelty_segments": summary.novelty_segments,
                    "food": summary.food.model_dump() if summary.food else None,
                    "segments": [s.model_dump() for s in summary.segments],
                    "period_metrics": {
                        k: [s.model_dump() for s in v]
                        for k, v in summary.period_metrics.items()
                    },
                    "processing": False,
                }},
                upsert=True,
            )
            logger.info("_text_summary_bg complete for %s/%s", device, date)
    except Exception as exc:
        logger.error("_text_summary_bg failed for %s/%s: %s", device, date, exc)
        DaySummaryRecord.update_one(
            {"date": date, "device": device},
            data={"$set": {"processing": False}},
            upsert=True,
        )


def _process_date_bg(device: str, date: str, reannotate: bool) -> None:
    """Background: run segmentation for a given date."""
    from sqlalchemy.orm import Session as _Session
    try:
        with _Session(_db_engine) as session:
            load_all_segments(session, device, date, skip_annotations=not reannotate)
        logger.info("_process_date_bg complete for %s/%s", device, date)
    except Exception as exc:
        logger.error("_process_date_bg failed for %s/%s: %s", device, date, exc)
    finally:
        DaySummaryRecord.update_one(
            {"date": date, "device": device},
            data={"$set": {"processing": False}},
            upsert=True,
        )


def process_segments(session: Session, date: str, device: str):
    blank_ids = set(
        ImageRecord.distinct(
            session, "segment_id", date=date, deleted=False, device=device, activity=""
        )
    )
    unclear_ids = set(
        ImageRecord.distinct(
            session,
            "segment_id",
            date=date,
            deleted=False,
            device=device,
            activity="Unclear",
        )
    )
    segment_ids = list(blank_ids | unclear_ids)

    print(f"Processing {len(segment_ids)} segments for date {date}.")
    all_summaries = _get_last_n_summaries(session, date, device, n=10)

    for _, segment_id in tqdm(
        enumerate(segment_ids), total=len(segment_ids), desc="Processing segments"
    ):
        if segment_id is None:
            continue

        thumbnails = [
            img.thumbnail
            for img in ImageRecord.find(
                session,
                segment_id=segment_id,
                deleted=False,
                device=device,
                sort="image_path",
                sort_desc=False,
            )
        ]

        new_description = describe_segment_task.delay(
            device, date, thumbnails, segment_id
        )
        all_summaries = [*all_summaries, new_description][-10:]

        DaySummaryRecord.update_one(
            {
                "date": date,
                "device": device,
            },
            data={"$set": {"updated": True}},
        )

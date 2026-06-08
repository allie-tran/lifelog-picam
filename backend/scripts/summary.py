# Summary of various activities in the day

import logging
from datetime import datetime, timedelta
from typing import Callable, List

import os
import numpy as np
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.orm import Session
from app_types import ActionType, CustomTarget, DaySummary, SummarySegment
from auth.ortho import apply_transformation, get_matrix
from constants import DIR, GROUPED_CATEGORIES
from database.models import Image, ImageEmbedding, HeartRateData, Location
from database.types import ImageRecord, _orm_to_lifelog
from llm import llm
from llm.gemini import MixedContent, get_visual_content
from scripts.date_utils import parse_date
from scripts.bio_stats import attach_bio_to_segments, hr_zone, _date_ns_window, _polar_ts_to_unix
from visual import clip_model

from scripts.segmentation import fetch_embeddings, pick_representative_index_for_segment

logger = logging.getLogger(__name__)

SocialClassifier = Callable[[np.ndarray], bool]
ActivityClassifier = Callable[[np.ndarray], str]
FoodDrinkClassifier = Callable[[np.ndarray], bool]
WorkBreakClassifier = Callable[[np.ndarray], str]

encoded_activities = clip_model.encode_texts(
    list(GROUPED_CATEGORIES.keys()),
)
encoded_activities_dict = {
    activity: encoded_activities[idx].cpu().numpy()
    for idx, activity in enumerate(GROUPED_CATEGORIES.keys())
}

encoded_prompts = {}

def encode_with_cache(session: Session, prompt: str, device: str):
    if prompt not in encoded_prompts:
        encoded = clip_model.encode_text(prompt, normalize=True)
        encoded_prompts[prompt] = apply_transformation(encoded, get_matrix(session, device))
    return encoded_prompts[prompt]


def summarize_lifelog_by_day(
    session,
    summary: DaySummary,
    targets: List[CustomTarget],
) -> DaySummary:
    """
    Summarize lifelog with custom targets: Bursts, Periods, and Binary.
    """
    paths = [
        record.image_path
        for record in ImageRecord.find(
            session,
            filter={"device": summary.device, "date": summary.date, "deleted": False}
        )
    ]
    paths, feats = fetch_embeddings(session, summary.device, paths)

    target_configs = []
    for target in targets:
        logger.debug("Encoding target: %s (%s)", target.name, target.action_type)
        name = target.name
        action_type = target.action_type
        encoded_query = encode_with_cache(session, f"a photo of {name}", summary.device)
        encoded_negative_query = encode_with_cache(session, f"a photo without {name}", summary.device)

        target_configs.append((name, action_type, encoded_query, encoded_negative_query))

        if action_type == ActionType.BINARY:
            summary.binary_metrics[name] = 0.0
        elif action_type == ActionType.BURST:
            summary.burst_metrics[name] = []

    if len(feats) == 0:
        logger.warning("No embeddings for %s on %s.", summary.device, summary.date)
        return summary
    all_feats = feats / np.linalg.norm(feats, axis=1, keepdims=True)
    summary.total_images = len(paths)

    for name, action_type, query_vec, neg_query_vec in target_configs:
        all_pos_sim = all_feats @ query_vec
        all_neg_sim = all_feats @ neg_query_vec
        is_present_array = all_pos_sim > all_neg_sim

        for idx, is_present in enumerate(is_present_array):
            if is_present:
                if action_type == ActionType.BINARY:
                    summary.binary_metrics[name] += 1
                elif action_type == ActionType.BURST:
                    basename = os.path.basename(paths[idx]).split(".")[0]
                    timestamp = parse_date(basename).timestamp()
                    if summary.burst_metrics[name] and timestamp - summary.burst_metrics[name][-1] < 30:
                        summary.burst_metrics[name][-1] = timestamp
                    else:
                        summary.burst_metrics[name].append(timestamp)

    period_targets = [
        target.name for target in targets if target.action_type == ActionType.PERIOD
    ]

    for target_name in period_targets:
        target_segments = [
            seg
            for seg in summary.segments
            if seg.activity.lower() == target_name.lower()
            or GROUPED_CATEGORIES.get(seg.activity) == target_name
        ]

        if not target_segments:
            continue

        target_segments.sort(key=lambda seg: seg.start_time)
        merged = []
        current_seg = target_segments[0]

        for next_seg in target_segments[1:]:
            if (next_seg.start_time - current_seg.end_time) <= timedelta(minutes=30):
                current_seg.end_time = next_seg.end_time
                current_seg.duration += next_seg.duration
            else:
                merged.append(current_seg)
                current_seg = next_seg
        merged.append(current_seg)

        query_vec = encode_with_cache(session, f"a photo of {target_name}", summary.device)
        for seg in merged:
            seg_paths, seg_feats = get_segment_data(session, summary, seg)
            rep_indices = pick_representative_index_for_segment(
                seg_paths, seg_feats, query_vec
            )
            seg.representative_images = [_orm_to_lifelog(img) for img in
                                         session.execute(
                    select(Image).where(
                        Image.device == summary.device,
                        Image.image_path.in_(rep_indices),
                    )
                ).scalars().all()]

            seg.representative_image = (
                seg.representative_images[0] if seg.representative_images else None
            )

        summary.period_metrics[target_name] = merged
        summary.custom_summaries[target_name] = generate_period_description(
            target_name, merged, summary.device
        )

    summary.total_minutes = sum(seg.duration / 60.0 for seg in summary.segments)
    for seg in summary.segments:
        category = GROUPED_CATEGORIES.get(seg.activity, "Unclear")
        summary.category_minutes[category] = summary.category_minutes.get(category, 0) + seg.duration / 60.0

    return summary


def generate_period_description(target_name: str, segments: List[SummarySegment], device: str) -> str:
    if not segments:
        return ""

    bytes_list = []
    times = []

    for segment in segments:
        rep_image = segment.representative_image
        if rep_image is not None:
            image_path = f"{DIR}/{device}/{rep_image.image_path}"
            try:
                with open(image_path, "rb") as f:
                    bytes_list.append(f.read())
                times.append(f"{segment.start_time} to {segment.end_time}")
            except FileNotFoundError:
                continue

    if not bytes_list:
        return f"Engaged in {target_name}."

    visual_contents = get_visual_content(bytes_list)
    time_contents = [
        MixedContent(type="text", content=f"Timeframe: {t}") for t in times
    ]

    combined_context = []
    for t_cont, v_cont in zip(time_contents, visual_contents):
        combined_context.extend([t_cont, v_cont])

    prompt = (
        f"Based on these images of '{target_name}', describe the activity briefly. "
        "Focus on the health-relevant aspects and nature of the task, environment, and any notable details. "
        "Use note-style, be objective, and keep it under 30 words. "
        "Ignore dates, keep time only. "
    )

    try:
        description = llm.generate_from_mixed_media(
            [MixedContent(type="text", content=prompt)] + combined_context
        )
        return str(description).strip()
    except Exception as e:
        logger.error("Error generating description for %s: %s", target_name, e)
        return f"Activity: {target_name} detected."


def get_segment_data(session, summary, segment):
    records = session.execute(
        select(Image.image_path).where(
            Image.device == summary.device,
            Image.timestamp >= segment.start_time,
            Image.timestamp <= segment.end_time,
        )
    )
    paths = [r.image_path for r in records]
    paths, seg_feats = fetch_embeddings(session, summary.device, paths)
    return paths, seg_feats


def time_to_ms(date_str, time_str):
    return (
        datetime.strptime(f"{date_str} {time_str}", "%Y-%m-%d %H:%M:%S").timestamp()
        * 1000
    )

class TempActivitySegment(BaseModel):
    activity: str
    start_time: datetime
    end_time: datetime
    image_paths: List[str]
    duration: int = 0
    location_name: str = ""


def _fetch_segment_locations(session, device: str, date: str) -> dict[int, str]:
    """
    Return {segment_id: most_common_location_display_name} for the given date/device.
    One query, grouped in Python.
    """
    from collections import Counter
    rows = session.execute(
        select(Image.segment_id, Location.name, Location.address)
        .join(Location, Image.location_id == Location.id)
        .where(
            Image.device == device,
            Image.date == date,
            Image.deleted == False,
            Image.segment_id.isnot(None),
        )
    ).all()

    seg_locs: dict[int, list[str]] = {}
    for seg_id, name, address in rows:
        display = name if name and name not in ("---", "Unknown Place", "") else (address or "")
        seg_locs.setdefault(seg_id, []).append(display)

    return {
        seg_id: Counter(names).most_common(1)[0][0]
        for seg_id, names in seg_locs.items()
        if names
    }


def _fetch_day_hr_rows(session, device_id: str, date: str) -> list:
    """Fetch all HeartRateData rows for device/date (Polar epoch)."""
    start_ns, end_ns = _date_ns_window(date)
    # device_id for bio sensors may differ — we try both the camera device_id and
    # any associated sensor device. For simplicity use the camera device_id as-is.
    return session.execute(
        select(HeartRateData)
        .where(
            HeartRateData.device_id == device_id,
            HeartRateData.time_stamp >= start_ns,
            HeartRateData.time_stamp < end_ns,
        )
        .order_by(HeartRateData.time_stamp.asc())
    ).scalars().all()


def create_day_timeline(session, device: str, date: str) -> list[SummarySegment]:
    records = session.execute(
        select(Image).where(
            Image.device == device,
            Image.date == date,
            Image.deleted == False,
            Image.segment_id != None,
        ).order_by(Image.timestamp.asc())
    ).fetchall()

    records = [_orm_to_lifelog(r.Image) for r in records]

    # Batch-fetch segment locations (one query)
    seg_to_location = _fetch_segment_locations(session, device, date)

    # Batch-fetch HR for the day (one query)
    hr_rows = _fetch_day_hr_rows(session, device, date)

    # Group by segment_id
    groups: dict = {}
    for record in records:
        sid = record.segment_id
        if sid not in groups:
            groups[sid] = {
                "activity": record.activity,
                "time": [record.timestamp],
                "image_paths": [record.image_path],
                "location_name": seg_to_location.get(sid, ""),
            }
        else:
            groups[sid]["time"].append(record.timestamp)
            groups[sid]["image_paths"].append(record.image_path)

    activities: list[TempActivitySegment] = []
    for sid, data in groups.items():
        activities.append(
            TempActivitySegment(
                activity=data.get("activity", "Unclear") or "Unclear",
                start_time=min(data["time"]),
                end_time=max(data["time"]),
                image_paths=data["image_paths"],
                location_name=data["location_name"],
            )
        )

    activities.sort(key=lambda x: x.start_time)

    if not activities:
        logger.info("No activities for %s/%s", device, date)
        return []

    earliest_hour = activities[0].start_time.hour
    latest_hour = activities[-1].end_time.hour + 1

    slot_duration = 15 * 60
    time_slots = [
        (s, s + slot_duration)
        for s in range(earliest_hour * 3600, latest_hour * 3600, slot_duration)
    ]

    summary_slots: list[SummarySegment] = []
    for slot_start, slot_end in time_slots:
        slot_start_time = datetime.strptime(date, "%Y-%m-%d") + timedelta(seconds=slot_start)
        slot_end_time = datetime.strptime(date, "%Y-%m-%d") + timedelta(seconds=slot_end)

        slot_activities = []
        slot_locations = []
        for temp_seg in activities:
            if temp_seg.start_time <= slot_end_time and temp_seg.end_time >= slot_start_time:
                slot_activities.append(temp_seg.activity)
                if temp_seg.location_name:
                    slot_locations.append(temp_seg.location_name)

        activity = "No Activity"
        if slot_activities:
            activity = max(set(slot_activities), key=slot_activities.count)

        from collections import Counter
        location_name = Counter(slot_locations).most_common(1)[0][0] if slot_locations else None

        summary_slots.append(
            SummarySegment(
                segment_index=None,
                activity=activity,
                start_time=slot_start_time,
                end_time=slot_end_time,
                duration=slot_duration,
                representative_image=None,
                representative_images=[],
                location_name=location_name,
            )
        )

    # Merge consecutive same-activity slots
    merged: list[SummarySegment] = []
    for slot in summary_slots:
        if merged and merged[-1].activity == slot.activity:
            merged[-1].end_time = slot.end_time
            merged[-1].duration += slot.duration
            # keep most common location
            if slot.location_name and not merged[-1].location_name:
                merged[-1].location_name = slot.location_name
        else:
            merged.append(slot)

    # Attach HR data to each merged segment
    if hr_rows:
        attach_bio_to_segments(merged, hr_rows)

    return merged


def summarize_day_by_text(session, day_summary: DaySummary) -> DaySummary:
    """
    Generate a natural-language highlight of the day.
    Includes activity descriptions AND location context.
    """
    try:
        records = session.execute(
            select(Image).where(
                Image.device == day_summary.device,
                Image.date == day_summary.date,
                Image.deleted == False,
                Image.segment_id != None,
            ).order_by(Image.timestamp.asc())
        ).fetchall()

        records = [_orm_to_lifelog(r.Image) for r in records]

        # Batch-fetch segment locations
        seg_to_location = _fetch_segment_locations(session, day_summary.device, day_summary.date)

        groups: dict = {}
        for record in records:
            sid = record.segment_id
            if sid not in groups:
                groups[sid] = {
                    "activity": record.activity,
                    "activity_description": record.activity_description,
                    "time": [record.timestamp],
                    "location": seg_to_location.get(sid, ""),
                }
            else:
                groups[sid]["time"].append(record.timestamp)

        raw_activities = []
        for data in groups.values():
            raw_activities.append({
                "activity": data["activity"],
                "activity_description": data["activity_description"],
                "start_time": min(data["time"]),
                "end_time": max(data["time"]),
                "location": data["location"],
            })
        raw_activities.sort(key=lambda x: x["start_time"])

        activity_lines = []
        for seg in raw_activities:
            if seg["activity"] == "No Activity":
                continue
            line = f'{seg["start_time"].strftime("%H:%M")}–{seg["end_time"].strftime("%H:%M")}: {seg["activity_description"] or seg["activity"]}'
            if seg["location"]:
                line += f' @ {seg["location"]}'
            activity_lines.append(line)

        day_summary_text = llm.generate_from_text(
            "What is the highlight of the day based on the following activities?\n"
            "Ignore unclear activities. Write 2-3 sentences in first person.\n"
            + "\n".join(activity_lines)
        )
        day_summary.summary_text = str(day_summary_text).strip()

    except Exception as e:
        logger.error("Failed to generate day summary text: %s", e)
        day_summary.summary_text = "No summary available."

    return day_summary

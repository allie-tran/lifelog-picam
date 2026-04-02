# Summary of various activities in the day

from datetime import datetime, timedelta
from typing import Callable, List

import os
import numpy as np
from pydantic import BaseModel
from sqlalchemy import select
from app_types import ActionType, CustomTarget, DaySummary, SummarySegment
from auth.ortho import apply_transformation, get_matrix
from constants import DIR, GROUPED_CATEGORIES
from database.models import Image, ImageEmbedding
from database.types import ImageRecord, _orm_to_lifelog
from llm import llm
from llm.gemini import MixedContent, get_visual_content
from visual import clip_model

from scripts.segmentation import fetch_embeddings, pick_representative_index_for_segment

SocialClassifier = Callable[[np.ndarray], bool]
ActivityClassifier = Callable[[np.ndarray], str]  # returns a category label
FoodDrinkClassifier = Callable[[np.ndarray], bool]
WorkBreakClassifier = Callable[[np.ndarray], str]  # returns "work", "break" or "other"

encoded_activities = clip_model.encode_texts(
    list(GROUPED_CATEGORIES.keys()),
)
encoded_activities_dict = {
    activity: encoded_activities[idx].cpu().numpy()
    for idx, activity in enumerate(GROUPED_CATEGORIES.keys())
}


def summarize_lifelog_by_day(
    session,
    summary: DaySummary,
    targets: List[CustomTarget],
) -> DaySummary:
    """
    Summarize lifelog with custom targets: Bursts, Periods, and Binary.
    """
    # Fetch all image paths and embeddings for the day
    paths = [
        record.image_path
        for record in ImageRecord.find(
            session,
            filter={"device": summary.device, "date": summary.date, "deleted": False}
        )
    ]
    paths, feats = fetch_embeddings(session, summary.device, paths)

    # 1. Handle BINARY and BURST targets (Frame-by-frame analysis)
    # We pre-encode the prompts for efficiency
    target_configs = []
    for target in targets:
        print(f"Encoding prompt for target: {target.name} with action type {target.action_type}")
        name = target.name
        action_type = target.action_type
        encoded_query = clip_model.encode_text(f"a photo of {name}", normalize=True)
        encoded_negative_query = clip_model.encode_text(f"a photo without {name}", normalize=True)

        encoded_query = apply_transformation(encoded_query, get_matrix(session, summary.device))
        encoded_negative_query = apply_transformation(encoded_negative_query, get_matrix(session, summary.device))

        target_configs.append((name, action_type, encoded_query, encoded_negative_query))

        if action_type == ActionType.BINARY:
            summary.binary_metrics[name] = 0.0  # Initialize binary metric
        elif action_type == ActionType.BURST:
            summary.burst_metrics[name] = []

    all_feats = feats / np.linalg.norm(feats, axis=1, keepdims=True)  # Normalize for cosine similarity
    summary.total_images = len(paths)

    for name, action_type, query_vec, neg_query_vec in target_configs:
        print(f"Processing target: {name} with action type {action_type}")
        all_pos_sim = all_feats @ query_vec
        all_neg_sim = all_feats @ neg_query_vec
        is_present_array = all_pos_sim > all_neg_sim  # Simple decision boundary

        for idx, is_present in enumerate(is_present_array):
            if is_present:
                if action_type == ActionType.BINARY:
                    summary.binary_metrics[name] += 1
                elif action_type == ActionType.BURST:
                    basename = os.path.basename(paths[idx]).split(".")[0]
                    if len(basename) > 15:
                        # timezone info
                        timestamp = datetime.strptime(basename, "%Y%m%d_%H%M%S_%Z").timestamp()
                    else:
                        timestamp = datetime.strptime(basename, "%Y%m%d_%H%M%S").timestamp()
                    if summary.burst_metrics[name] and timestamp - summary.burst_metrics[name][-1] < 30:
                        summary.burst_metrics[name][-1] = timestamp
                    else:
                        summary.burst_metrics[name].append(timestamp)

    # 2. Handle PERIOD targets (Segment aggregation)
    period_targets = [
        target.name for target in targets if target.action_type == ActionType.PERIOD
    ]

    for target_name in period_targets:
        # Filter segments where activity matches the target
        target_segments = [
            seg
            for seg in summary.segments
            if seg.activity.lower() == target_name.lower()
            or GROUPED_CATEGORIES.get(seg.activity) == target_name
        ]

        print(f"Found {len(target_segments)} segments for target '{target_name}' before merging.")

        if not target_segments:
            continue

        # Merge Logic (reused from your original food/drink logic)
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

        # Attach Visuals and LLM Summaries for the Period
        query_vec = clip_model.encode_text(f"a photo of {target_name}", normalize=True)
        for seg in merged:
            # (Selection logic for representative images remains same as your snippet)
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

        # Optional: Generate text summary for this specific period
        summary.custom_summaries[target_name] = generate_period_description(
            target_name, merged, summary.device
        )

    # Finalize totals
    summary.total_minutes = sum(seg.duration / 60.0 for seg in summary.segments)

    # Categories Minutes
    for seg in summary.segments:
        category = GROUPED_CATEGORIES.get(seg.activity, "Unclear")
        summary.category_minutes[category] = summary.category_minutes.get(category, 0) + seg.duration / 60.0

    return summary


def generate_period_description(target_name: str, segments: List[SummarySegment], device: str) -> str:
    """
    Generates a concise LLM summary for a specific target period (e.g., 'Eating', 'Working').
    """
    if not segments:
        return ""

    bytes_list = []
    times = []

    # 1. Collect representative images and timeframes for the LLM context
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

    # 2. Prepare multi-modal content for the LLM
    visual_contents = get_visual_content(bytes_list)
    time_contents = [
        MixedContent(type="text", content=f"Timeframe: {t}") for t in times
    ]

    # Interleave time and images
    combined_context = []
    for t_cont, v_cont in zip(time_contents, visual_contents):
        combined_context.extend([t_cont, v_cont])

    # 3. Request specialized summary based on the target name
    prompt = (
        f"Based on these images of '{target_name}', describe the activity briefly. "
        "Focus on the health-relevant aspects and nature of the task, environment, and any notable details that are useful for understanding the context of this activity. "
        "Use note-style, be objective, and keep it under 30 words. "
        "Ignore dates, keep time only. "
    )

    try:
        description = llm.generate_from_mixed_media(
            [MixedContent(type="text", content=prompt)] + combined_context  # type: ignore
        )
        return str(description).strip()
    except Exception as e:
        print(f"Error generating description for {target_name}: {e}")
        return f"Activity: {target_name} detected."



def get_segment_data(session, summary, segment):
    # Helper to fetch embeddings for a specific time range
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


def create_day_timeline(session, device: str, date: str):
    records = session.execute(
        select(Image).where(
            Image.device == device,
            Image.date == date,
            Image.deleted == False,
            Image.segment_id != None,
        ).order_by(Image.timestamp.asc())
        ).fetchall()

    records = [_orm_to_lifelog(r.Image) for r in records]

    # Group by segment_id and aggregate activities, start_time, end_time, and image_paths
    groups = {}
    for record in records:
        if record.segment_id not in groups:
            groups[record.segment_id] = {
                "activity": record.activity,
                "time": [record.timestamp],
                "image_paths": [record.image_path],
            }
        else:
            groups[record.segment_id]["time"].append(record.timestamp)
            groups[record.segment_id]["image_paths"].append(record.image_path)

    activities: list[TempActivitySegment] = []
    for data in groups.values():
        activities.append(
            TempActivitySegment(
                activity=data.get("activity", "Unclear") or "Unclear",
                start_time=min(data.get("time", [datetime.now()])),
                end_time=max(data.get("time", [datetime.now()])),
                image_paths=data.get("image_paths", [])
                )
        )

    # Sort activities by start_time
    activities.sort(key=lambda x: x.start_time)

    print("Aggregated activities for day summary.")
    if not activities:
        print("No activities found for the day.")
        return []

    # Predefine a grid of time slots (e.g., every 30 minutes)
    earliest_hour = 0
    latest_hour = 24
    if activities:
        earliest_hour = activities[0].start_time.hour
        latest_hour = activities[-1].end_time.hour + 1

    print("Creating time slots from", earliest_hour, "to", latest_hour)
    time_slots = []
    slot_duration = 10 * 60

    for slot_start in range(
        earliest_hour * 60 * 60, latest_hour * 60 * 60, slot_duration
    ):
        slot_end = slot_start + slot_duration
        time_slots.append((slot_start, slot_end))

    summary = []
    for slot_start, slot_end in time_slots:
        slot_activities = []
        slot_start_time = datetime.strptime(date, "%Y-%m-%d") + timedelta(seconds=slot_start)
        slot_end_time = datetime.strptime(date, "%Y-%m-%d") + timedelta(seconds=slot_end)

        seg_paths = []
        for temp_segment in activities:
            if (
                temp_segment.start_time <= slot_end_time and temp_segment.end_time >= slot_start_time
            ):
                slot_activities.append(temp_segment.activity)
                seg_paths.extend(temp_segment.image_paths)

        if slot_activities:
            # Choose the most frequent activity in the slot
            activity = max(set(slot_activities), key=slot_activities.count)
        else:
            activity = "No Activity"

        if seg_paths:
            # Get features
            feats = (
                session.execute(
                    select(ImageEmbedding.embedding, Image.image_path).where(
                        Image.image_path.in_(seg_paths),
                    ).join(Image, ImageEmbedding.image_id == Image.id)
                )
            )
            image_to_feats = {row.image_path: row.embedding for row in feats}
            seg_feats = np.array([image_to_feats[path] for path in seg_paths])

            representative_image_paths = pick_representative_index_for_segment(
                seg_paths,
                seg_feats,
                encoded_activities_dict.get(activity),
            )
            representative_image = session.execute(select(Image).where(
                Image.device == device,
                Image.image_path == representative_image_paths[0],
            )).scalar_one_or_none()
            representative_image = _orm_to_lifelog(representative_image) if representative_image else None

            representative_images = session.execute(
                select(Image).where(
                     Image.device == device,
                     Image.image_path.in_(representative_image_paths),
                ).order_by(Image.timestamp.asc())
            ).scalars().all()
            representative_images = [
                _orm_to_lifelog(img) for img in representative_images
            ]
        else:
            representative_image = None
            representative_images = []

        summary.append(
            SummarySegment(
                segment_index=None,
                activity=activity,
                start_time=slot_start_time,
                end_time=slot_end_time,
                duration=slot_duration,
                representative_image=representative_image,
                representative_images=list(representative_images),
            )
        )

    # Merge consecutive segments with the same activity
    merged_summary = []
    for temp_segment in summary:
        if merged_summary and merged_summary[-1].activity == temp_segment.activity:
            # Merge with the previous segment
            merged_summary[-1].end_time = temp_segment.end_time
            merged_summary[-1].duration += temp_segment.duration
            merged_summary[-1].representative_images.extend(
                temp_segment.representative_images
            )
        else:
            merged_summary.append(temp_segment)

    return merged_summary


def summarize_day_by_text(session, day_summay: DaySummary):
    try:
        records = session.execute(
            select(Image).where(
                Image.device == day_summay.device,
                Image.date == day_summay.date,
                Image.deleted == False,
                Image.segment_id != None,
            ).order_by(Image.timestamp.asc())
        ).fetchall()

        recods = [_orm_to_lifelog(r.Image) for r in records]
        groups = {}
        for record in recods:
            if record.segment_id not in groups:
                groups[record.segment_id] = {
                    "activity": record.activity,
                    "activity_description": record.activity_description,
                    "time": [record.timestamp],
                }
            else:
                groups[record.segment_id]["time"].append(record.timestamp)

        raw_activities = []
        for data in groups.values():
            raw_activities.append({
                "activity": data["activity"],
                "activity_description": data["activity_description"],
                "start_time": min(data["time"]),
                "end_time": max(data["time"]),
            })
        raw_activities.sort(key=lambda x: x["start_time"])
        day_summary = llm.generate_from_text(
            "What are 3 key activities I did during the day? Use note-style, avoid full sentences, less than 50 words in total, and focus on key activities.\n"
            "Ignore unclear activities.\n"
            + "\n".join(
                [
                    f'{seg["start_time"]} to {seg["end_time"]}: {seg["activity_description"]}'
                    for seg in raw_activities
                    if seg["activity"] != "No Activity"
                ]
            )
        )
        day_summary = str(day_summary).strip()

    except Exception as e:
        trace = str(e)
        print("Failed to generate day summary:", trace)
        day_summary = "No summary available."

    day_summay.summary_text = day_summary
    return day_summay

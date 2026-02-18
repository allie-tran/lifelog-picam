# Summary of various activities in the day

from datetime import datetime, timedelta
from typing import Callable, Dict, List, Tuple

import numpy as np
from app_types import ActionType, CLIPFeatures, CustomFastAPI, CustomTarget, DaySummary, SummarySegment
from constants import DIR, GROUPED_CATEGORIES, SEARCH_MODEL
from database.types import ImageRecord
from database.vector_database import fetch_embeddings
from llm import llm
from llm.gemini import MixedContent, get_visual_content
from visual import clip_model

from scripts.clip_classifier import ClipPromptClassifier
from scripts.segmentation import pick_representative_index_for_segment

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
    summary: DaySummary,
    features: CLIPFeatures,
    targets: List[CustomTarget],
    *,
    seconds_per_image: int = 10,
) -> DaySummary:
    """
    Summarize lifelog with custom targets: Bursts, Periods, and Binary.
    """
    collection = features.collection

    # Fetch all image paths and embeddings for the day
    paths = [
        record.image_path
        for record in ImageRecord.find(
            filter={"device": summary.device, "date": summary.date, "deleted": False}
        )
    ]
    paths, feats = fetch_embeddings(collection, paths, summary.device)

    # 1. Handle BINARY and BURST targets (Frame-by-frame analysis)
    # We pre-encode the prompts for efficiency
    target_configs = []
    for target in targets:
        print(f"Encoding prompt for target: {target.name} with action type {target.action_type}")
        name = target.name
        action_type = target.action_type
        encoded_query = clip_model.encode_text(f"a photo of {name}", normalize=True)
        encoded_negative_query = clip_model.encode_text(f"a photo without {name}", normalize=True)
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
                    timestamp = float(paths[idx].split("_")[-1].replace(".jpg", ""))
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
            current_end = datetime.strptime(current_seg.end_time, "%H:%M:%S")
            next_start = datetime.strptime(next_seg.start_time, "%H:%M:%S")
            if (next_start - current_end).total_seconds() <= 30 * 60:
                current_seg.end_time = next_seg.end_time
                current_seg.duration += next_seg.duration
            else:
                merged.append(current_seg)
                current_seg = next_seg
        merged.append(current_seg)

        # Attach Visuals and LLM Summaries for the Period
        query_vec = clip_model.encode_text(f"a representative photo of {target_name}")
        for seg in merged:
            # (Selection logic for representative images remains same as your snippet)
            seg_paths, seg_feats = get_segment_data(summary, seg, collection)
            rep_indices = pick_representative_index_for_segment(
                seg_paths, seg_feats, query_vec
            )
            seg.representative_images = list(
                ImageRecord.find({"image_path": {"$in": rep_indices}})
            )
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
        "Focus on the specific nature of the task, environment, and any notable details. "
        "Use note-style, be objective, and keep it under 30 words."
    )

    try:
        description = llm.generate_from_mixed_media(
            [MixedContent(type="text", content=prompt)] + combined_context  # type: ignore
        )
        return str(description).strip()
    except Exception as e:
        print(f"Error generating description for {target_name}: {e}")
        return f"Activity: {target_name} detected."



def get_segment_data(summary, segment, collection):
    # Helper to fetch embeddings for a specific time range
    records = ImageRecord.find(
        filter={
            "device": summary.device,
            "timestamp": {
                "$gte": time_to_ms(summary.date, segment.start_time),
                "$lte": time_to_ms(summary.date, segment.end_time),
            },
        }
    )
    paths = [r.image_path for r in records]
    return fetch_embeddings(collection, paths, summary.device)


def time_to_ms(date_str, time_str):
    return (
        datetime.strptime(f"{date_str} {time_str}", "%Y-%m-%d %H:%M:%S").timestamp()
        * 1000
    )


def create_day_timeline(app: CustomFastAPI, device: str, date: str):
    activities = ImageRecord.aggregate(
        [
            {
                "$match": {
                    "date": date,
                    "deleted": False,
                    "segment_id": {"$ne": None},
                    "device": device,
                }
            },
            {
                "$group": {
                    "_id": "$segment_id",
                    "activity": {"$first": "$activity"},
                    "start_time": {"$min": "$timestamp"},
                    "end_time": {"$max": "$timestamp"},
                    "image_paths": {"$push": "$image_path"},
                }
            },
            {"$sort": {"start_time": 1}},
        ]
    )

    print("Aggregated activities for day summary.")
    activities = list(activities)

    if not activities:
        print("No activities found for the day.")
        return []

    # Predefine a grid of time slots (e.g., every 30 minutes)
    earliest_hour = 0
    latest_hour = 24
    if activities:
        earliest_hour = datetime.fromtimestamp(activities[0].start_time / 1000).hour
        latest_hour = datetime.fromtimestamp(activities[-1].end_time / 1000).hour + 1

    print("Creating time slots from", earliest_hour, "to", latest_hour)
    time_slots = []
    slot_duration = 5 * 60 * 1000
    for slot_start in range(
        earliest_hour * 60 * 60 * 1000, latest_hour * 60 * 60 * 1000, slot_duration
    ):
        slot_end = slot_start + slot_duration
        time_slots.append((slot_start, slot_end))

    summary = []
    for slot_start, slot_end in time_slots:
        slot_activities = []

        seg_paths = []
        for segment in activities:
            segment = segment.dict()
            if (
                segment["end_time"]
                >= slot_start + datetime.strptime(date, "%Y-%m-%d").timestamp() * 1000
                and segment["start_time"]
                < slot_end + datetime.strptime(date, "%Y-%m-%d").timestamp() * 1000
            ):
                slot_activities.append(segment["activity"] or "Unclear")
                seg_paths.extend(segment["image_paths"])

        if slot_activities:
            # Choose the most frequent activity in the slot
            activity = max(set(slot_activities), key=slot_activities.count)
        else:
            activity = "No Activity"

        start_time_str = (
            datetime.strptime(date, "%Y-%m-%d") + timedelta(milliseconds=slot_start)
        ).strftime("%H:%M:%S")
        end_time_str = (
            datetime.strptime(date, "%Y-%m-%d") + timedelta(milliseconds=slot_end)
        ).strftime("%H:%M:%S")

        if seg_paths:
            seg_paths, seg_feats = fetch_embeddings(
                app.features[device][SEARCH_MODEL].collection, seg_paths,
                device,
            )
            representative_image_paths = pick_representative_index_for_segment(
                seg_paths,
                seg_feats,
                encoded_activities_dict.get(activity),
            )
            representative_image = ImageRecord.find_one(
                filter={
                    "device": device,
                    "image_path": representative_image_paths[0],
                }
            )
            representative_images = ImageRecord.find(
                filter={
                    "device": device,
                    "image_path": {"$in": representative_image_paths},
                },
                sort=[("timestamp", 1)],
            )
        else:
            representative_image = None
            representative_images = []

        summary.append(
            SummarySegment(
                segment_index=None,
                activity=activity,
                start_time=start_time_str,
                end_time=end_time_str,
                duration=int(slot_duration / 1000),
                representative_image=representative_image,
                representative_images=list(representative_images),
            )
        )

    # Merge consecutive segments with the same activity
    merged_summary = []
    for segment in summary:
        if merged_summary and merged_summary[-1].activity == segment.activity:
            # Merge with the previous segment
            merged_summary[-1].end_time = segment.end_time
            merged_summary[-1].duration += segment.duration
            merged_summary[-1].representative_images.extend(
                segment.representative_images
            )
        else:
            merged_summary.append(segment)

    return merged_summary


def summarize_day_by_text(day_summay: DaySummary):
    try:
        raw_activities = ImageRecord.aggregate(
            [
                {
                    "$match": {
                        "date": day_summay.date,
                        "deleted": False,
                        "segment_id": {"$ne": None},
                        "device": day_summay.device,
                    }
                },
                {
                    "$group": {
                        "_id": "$segment_id",
                        "activity": {"$first": "$activity"},
                        "activity_description": {"$first": "$activity_description"},
                        "start_time": {"$min": "$timestamp"},
                        "end_time": {"$max": "$timestamp"},
                    }
                },
                {"$sort": {"start_time": 1}},
            ]
        )

        day_summary = llm.generate_from_text(
            "What are 3 key activities I did during the day? Use note-style, avoid full sentences, less than 50 words in total, and focus on key activities.\n"
            "Ignore unclear activities.\n"
            + "\n".join(
                [
                    f"{seg.start_time} to {seg.end_time}: {seg.activity_description}"
                    for seg in raw_activities
                    if seg.activity != "No Activity"
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

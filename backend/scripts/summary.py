# Summary of various activities in the day

from collections import defaultdict
from datetime import datetime, timedelta
from typing import Callable, Dict, List, Optional

import numpy as np
from app_types import CLIPFeatures, CustomFastAPI, DaySummary, SummarySegment
from constants import DIR, GROUPED_CATEGORIES
from database.types import ImageRecord
from visual import siglip_model

from scripts.clip_classifier import ClipPromptClassifier
from llm import llm, MixedContent, get_visual_content
from scripts.segmentation import pick_representative_index_for_segment

SocialClassifier = Callable[[np.ndarray], bool]
ActivityClassifier = Callable[[np.ndarray], str]  # returns a category label
FoodDrinkClassifier = Callable[[np.ndarray], bool]
WorkBreakClassifier = Callable[[np.ndarray], str]  # returns "work", "break" or "other"

encoded_activities = siglip_model.encode_texts(
    list(GROUPED_CATEGORIES.keys()),
)
encoded_activities_dict = {
    activity: encoded_activities[idx].cpu().numpy()
    for idx, activity in enumerate(GROUPED_CATEGORIES.keys())
}


def summarize_lifelog_by_day(
    summary: DaySummary,
    features: CLIPFeatures,
    *,
    seconds_per_image: int = 10,
) -> DaySummary:
    """
    Aggregate lifelog information into per-day summaries.

    Parameters
    ----------
    features : Dict[device_id, np.ndarray]
        Image feature vectors, shape (N_images, D).
    image_paths : Dict[device_id, List[str]]
        Image paths aligned with features for each device.
    image_records : Iterable[ImageRecord]
        Records giving at least (image_path, date).
    seconds_per_image : int
        Assumed time represented by one image (e.g. 30 for 1 image every 30 seconds).
    social_classifier : callable
        f(vec) -> True if social, False if alone.
    activity_classifier : callable
        f(vec) -> activity category label, e.g. "work", "leisure", "exercise".
    food_drink_classifier : callable
        f(vec) -> True if the image involves food/drink.
    work_break_classifier : callable
        f(vec) -> label in {"work", "break", "other"}.

    Returns
    -------
    Dict[date_str, DailySummary]
    """
    feats = features.features
    paths = features.image_paths
    image_paths_to_index = features.image_paths_to_index

    minutes_per_image = seconds_per_image / 60.0

    for vec, path in zip(feats, paths):
        date_str: Optional[str] = path.split("/")[0]
        if date_str != summary.date:
            continue

        # --- Run your classifiers ---
        is_social = social_classifier(vec)

        # --- 1. Social vs alone ---
        if is_social:
            summary.social_minutes += minutes_per_image
        else:
            summary.alone_minutes += minutes_per_image

        # Bookkeeping
        summary.total_images += 1

    # count activity based on segments
    activity_minutes: Dict[str, float] = defaultdict(float)
    eating_segments = []
    for segment in summary.segments:
        activity = segment.activity
        duration_minutes = segment.duration / 60.0
        theme = GROUPED_CATEGORIES.get(activity, "Miscellaneous")
        activity_minutes[theme] += duration_minutes
        if theme == "Food & Drink":
            eating_segments.append(segment)

    # summarize category minutes
    summary.category_minutes = activity_minutes

    # --- Summarize food & drink patterns ---
    # merge eating segments
    summary.food_drink_minutes = sum(
        segment.duration / 60.0 for segment in eating_segments
    )
    encoded_query = siglip_model.encode_text(
        "a first-person photo of someone eating or drinking",
    )
    merged_segments = []
    if eating_segments:
        eating_segments.sort(key=lambda seg: seg.start_time)
        current_seg = eating_segments[0]
        for seg in eating_segments[1:]:
            current_end = datetime.strptime(current_seg.end_time, "%H:%M:%S")
            next_start = datetime.strptime(seg.start_time, "%H:%M:%S")
            # If the next segment starts within 30 minutes of the current segment ending, merge them
            if (next_start - current_end).total_seconds() <= 30 * 60:
                current_seg.end_time = seg.end_time
                current_seg.duration += seg.duration
            else:
                merged_segments.append(current_seg)
                current_seg = seg

        merged_segments.append(current_seg)

    # Pick representative images for merged segments
    for current_seg in merged_segments:
        image_paths = ImageRecord.find(
            filter={
                "device": summary.device,
                "timestamp": {
                    "$gte": datetime.strptime(
                        f"{summary.date} {current_seg.start_time}", "%Y-%m-%d %H:%M:%S"
                    ).timestamp()
                    * 1000,
                    "$lte": datetime.strptime(
                        f"{summary.date} {current_seg.end_time}", "%Y-%m-%d %H:%M:%S"
                    ).timestamp()
                    * 1000,
                },
                "deleted": False,
            },
            sort=[("timestamp", 1)],
        )
        indices = [
            image_paths_to_index[img.image_path]
            for img in image_paths
            if img.image_path in image_paths_to_index
        ]
        if not indices:
            continue

        representative_image_paths = pick_representative_index_for_segment(
            indices,
            paths,
            feats,
            query_embedding=encoded_query,
        )
        representative_image = ImageRecord.find_one(
            filter={
                "device": summary.device,
                "image_path": representative_image_paths[0],
            }
        )
        representative_images = ImageRecord.find(
            filter={
                "device": summary.device,
                "image_path": {"$in": representative_image_paths},
            },
            sort=[("timestamp", 1)],
        )
        current_seg.representative_image = representative_image
        current_seg.representative_images = list(representative_images)

    summary.food_drink_segments = merged_segments

    if summary.food_drink_minutes > 0:
        # get bytes
        bytes_list = []
        times = []
        for segment in summary.food_drink_segments:
            representative_image = segment.representative_image
            if representative_image is not None:
                with open(
                    f"{DIR}/{summary.device}/{representative_image.image_path}", "rb"
                ) as f:
                    bytes_list.append(f.read())
            times.append(f"{segment.start_time} to {segment.end_time}")

        visual_contents = get_visual_content(bytes_list)
        time_contents = [
            MixedContent(type="text", content=time_str) for time_str in times
        ]
        both_contents = []
        for time_content, visual_content in zip(time_contents, visual_contents):
            both_contents.extend([time_content, visual_content])

        food_drink_summary = llm.generate_from_mixed_media(
            [
                MixedContent(
                    type="text",
                    content="Based on the above images, describe the food and drink items in brief, most focusing on judging the diet (what food, specifically), timing, duration (specific), and environment of eating and drinking activities during the day. Use note-style if possible, less than 30 words.",
                )
            ]
            + both_contents
        )
        summary.food_drink_summary = str(food_drink_summary).strip()

    # Check the actual minutes counted from all the segments
    total_segment_minutes = sum(segment.duration / 60.0 for segment in summary.segments)
    summary.total_minutes = total_segment_minutes

    return summary


# Use descriptions that match lifelog context
social_class_names = [
    "other people around",
    "in a group",
    "in a meeting",
    "with friends",
    "with family",
]
alone_class_names = ["alone", "by myself"]

# For a binary decision, it's convenient to group prompts into two logical labels:
social_vs_alone_labels = ["social", "alone"]

social_vs_alone_prompts = {
    "social": social_class_names,
    "alone": alone_class_names,
}


def build_grouped_clip_classifier(
    grouped_prompts: Dict[str, List[str]],
) -> ClipPromptClassifier:
    """
    grouped_prompts: {"label": ["prompt phrase", ...], ...}
    """
    # We implement this by giving each label its own "composite prompt"
    class_names = list(grouped_prompts.keys())
    # Wrap a small subclass that overrides _build_text_embeddings
    clf = ClipPromptClassifier(
        class_names=class_names,
        prompt_templates=["a photo of {}", "a lifelog image of {}"],
    )
    return clf


# Build the classifier once:
social_alone_clf = build_grouped_clip_classifier(
    grouped_prompts=social_vs_alone_prompts,
)


def social_classifier(vec: np.ndarray) -> bool:
    """
    vec: shape (D,)
    Returns True if 'social', False if 'alone'.
    """
    probs = social_alone_clf.predict_proba_from_features(vec[None, :])[0]
    label = social_alone_clf.class_names[probs.argmax()]
    return label == "social"


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
        indices = []
        for segment in activities:
            segment = segment.dict()
            if (
                segment["end_time"]
                >= slot_start + datetime.strptime(date, "%Y-%m-%d").timestamp() * 1000
                and segment["start_time"]
                < slot_end + datetime.strptime(date, "%Y-%m-%d").timestamp() * 1000
            ):
                slot_activities.append(segment["activity"] or "Unclear")
                indices.extend(
                    [
                        app.features[device]["siglip"].image_paths_to_index.get(img_path)
                        for img_path in segment["image_paths"]
                    ]
                )

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

        if indices:
            representative_image_paths = pick_representative_index_for_segment(
                indices,
                app.features[device]["siglip"].image_paths,
                app.features[device]["siglip"].features,
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
        if (
            merged_summary
            and merged_summary[-1].activity == segment.activity
        ):
            # Merge with the previous segment
            merged_summary[-1].end_time = segment.end_time
            merged_summary[-1].duration += segment.duration
            merged_summary[-1].representative_images.extend(segment.representative_images)
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

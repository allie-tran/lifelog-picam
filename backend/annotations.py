from datetime import datetime, timedelta

from fastapi import APIRouter, BackgroundTasks

from app_types import DaySummary, SummarySegment
from endpoints.database import process_segments
from database.types import DaySummaryRecord, ImageRecord
from llm import llm, MixedContent, get_visual_content

annotations = APIRouter()

@annotations.get("/process-date")
def process_date(date: str, background_tasks: BackgroundTasks):
    background_tasks.add_task(process_segments, date)
    return {"message": f"Processing segments for date {date} in background."}


@annotations.get("/day-summary")
def get_day_summary(date: str):
    activities = ImageRecord.aggregate(
        [
            {"$match": {"date": date, "deleted": False, "segment_id": {"$ne": None}}},
            {
                "$group": {
                    "_id": "$segment_id",
                    "activity": {"$first": "$activity"},
                    "start_time": {"$min": "$timestamp"},
                    "end_time": {"$max": "$timestamp"},
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
    slot_duration = 15 * 60 * 1000
    for slot_start in range(
        earliest_hour * 60 * 60 * 1000, latest_hour * 60 * 60 * 1000, slot_duration
    ):
        slot_end = slot_start + slot_duration
        time_slots.append((slot_start, slot_end))

    summary = []
    for slot_start, slot_end in time_slots:
        slot_activities = []
        for segment in activities:
            segment = segment.dict()
            if (
                segment["end_time"]
                >= slot_start + datetime.strptime(date, "%Y-%m-%d").timestamp() * 1000
                and segment["start_time"]
                < slot_end + datetime.strptime(date, "%Y-%m-%d").timestamp() * 1000
            ):
                slot_activities.append(segment["activity"] or "Unclear")

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

        summary.append(
            SummarySegment(
                segment_index=None,
                activity=activity,
                start_time=start_time_str,
                end_time=end_time_str,
                duration=int(slot_duration / 1000),
            )
        )

    updated = True
    day_summary_record = DaySummaryRecord.find_one({"date": date})
    if (
        day_summary_record
        and not day_summary_record.updated
        and day_summary_record.summary_text
    ):
        day_summary = day_summary_record.summary_text
        updated = False
    else:
        try:
            raw_activities = ImageRecord.aggregate(
                [
                    {
                        "$match": {
                            "date": date,
                            "deleted": False,
                            "segment_id": {"$ne": None},
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
                "Create a summary of the activities performed during the day based on the following segments. Make it concise and informative. Such as: you spent the morning working, had lunch at 1 PM, spent the afternoon relaxing, and in the evening you went for a walk.\n"
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
            updated = False

        except Exception as e:
            trace = str(e)
            print("Failed to generate day summary:", trace)
            day_summary = "No summary available."

    summary = DaySummary(
        date=date, segments=summary, summary_text=day_summary, updated=updated
    )
    DaySummaryRecord.update_one(
        {"date": date},
        {"$set": summary.model_dump(by_alias=True)},
        upsert=True,
    )

    return summary

from collections import defaultdict
from google.genai.errors import ClientError, ServerError
import time
import random
import traceback

from constants import DIR
from database.types import ImageRecord
from scripts.llm import llm_model, MixedContent, get_visual_content
from rich import print as rprint

CATEGORIES = {
    # Work – Research & Writing
    "Paper Writing": "#1f618d",
    "Grant Writing": "#1f618d",
    "Coding / Experimenting": "#1f618d",
    "Data Analysis": "#1f618d",
    "Reading Papers": "#1f618d",
    "Email & Admin": "#1f618d",
    "Supervising Students": "#1f618d",
    "Giving Feedback": "#1f618d",

    # Meetings & Collaboration
    "Team Meeting": "#117864",
    "One-to-One Meeting": "#117864",
    "Conference Call": "#117864",
    "Seminar / Talk": "#117864",
    "Conference / Workshop": "#117864",
    "Presentation Prep": "#117864",

    # Teaching & Outreach
    "Lecturing": "#f39c12",
    "Lab / Tutorial": "#f39c12",
    "Grading / Assessment": "#f39c12",
    "Course Prep": "#f39c12",
    "Outreach / Public Talk": "#f39c12",

    # Travel
    "Commuting": "#7f8c8d",
    "Walking on Campus": "#7f8c8d",
    "Travelling (Train)": "#7f8c8d",
    "Travelling (Plane)": "#7f8c8d",
    "Conference Travel": "#7f8c8d",
    "Packing / Unpacking": "#7f8c8d",

    # Food & Drink
    "Eating": "#e67e22",
    "Drinking": "#e67e22",
    "Making Coffee": "#e67e22",
    "Making Tea": "#e67e22",
    "Cooking at Home": "#e67e22",
    "Eating Out": "#e67e22",

    # Leisure & Wellbeing
    "Reading": "#9b59b6",
    "Watching TV / Series": "#9b59b6",
    "Listening to Music": "#9b59b6",
    "Exercise / Gym": "#9b59b6",
    "Walking for Leisure": "#9b59b6",
    "Photography / Journaling": "#9b59b6",
    "Relaxing / Doing Nothing": "#9b59b6",

    # Social & Personal
    "Talking with Friends": "#c0392b",
    "Video Call with Partner": "#c0392b",
    "Family Time": "#c0392b",
    "Shopping / Errands": "#c0392b",
    "House Cleaning": "#c0392b",
    "Laundry / Chores": "#c0392b",
    "Organizing Workspace": "#c0392b",

    # Sleep / Downtime
    "Sleeping": "#2c3e50",
    "Resting": "#2c3e50",
    "Napping": "#2c3e50",

    # Miscellaneous
    "Transit / Waiting": "#95a5a6",
    "Taking Notes": "#95a5a6",
    "Unclear Activity": "#95a5a6",
    "No Activity": "#000000",
}


def get_description_from_frames(instructions: list[str], image_bytes: list[bytes]) -> str:
    description = llm_model.generate_from_mixed_media(
        get_visual_content(image_bytes) + [MixedContent(type="text", content=instructions[0])],
    )
    return str(description).strip()

def get_rewritten_description(description, instructions: list[str] = []):
    if len(instructions) >= 2 and instructions[1]:
        prompt = f"Rewrite these sentences:\n{description}.\n\n{instructions[1]}"
        rewritten_response: str = llm_model.generate_from_text(prompt)  # type: ignore
        return rewritten_response.strip()
    else:
        # If no instructions are provided, just return the description
        return description


def describe_segment(segment: list[str], segment_idx: int):
    image_bytes = []
    if len(segment) > 20:
        segment = [segment[i] for i in sorted(random.sample(range(len(segment)), 20))]

    final_category = "Unclear"
    for image_path in segment:
        img = open(f"{DIR}/{image_path}", 'rb').read()
        image_bytes.append(img)

    description = ""
    tries = 0
    while True:
        if tries >= 5:
            rprint("Max retries reached. Skipping segment.")
            break
        try:
            tries += 1
            description = get_description_from_frames([
                f"Classify this segment into one of the following categories: {', '.join(CATEGORIES.keys())}. ",
                f"Reply with only the category name with no additional text."
                "If you are unsure, reply with 'Unclear'."
            ], image_bytes)
            break
        except KeyboardInterrupt as e:
            raise e
        except ClientError as e:
            for detail in e.details["error"]["details"]:
                if "retryDelay" in detail:
                    rprint(f"Retry after: {detail['retryDelay']}")
                    delay = detail['retryDelay']
                    delay = int(delay.replace('s', '')) + 10
                    time.sleep(delay)
        except ServerError:
            time.sleep(10)

    possible_categories = [c for c in CATEGORIES if c.lower() in str(description).lower()]
    if possible_categories:
        final_category = possible_categories[0]

    print(f"Segment {segment_idx}: {final_category}")
    ImageRecord.update_many(
        filter={"segment_id": segment_idx},
        data={"$set": {"activity": final_category}}
    )

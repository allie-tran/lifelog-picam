import random
import time
import traceback
import io
from PIL import Image

from constants import THUMBNAIL_DIR
from database.types import ImageRecord
from google.genai.errors import ClientError, ServerError
from partialjson.json_parser import JSONParser
from rich import print as rprint

from llm import MixedContent, get_visual_content, llm
from constants import CATEGORIES

parser = JSONParser()


def get_description_from_frames(
    instructions: list[str], image_bytes: list[bytes]
) -> dict[str, str] | None:
    description = llm.generate_from_mixed_media(
        get_visual_content(image_bytes)
        + [MixedContent(type="text", content=instructions) for instructions in instructions]
    )
    description = str(description)
    description_text = description.strip()
    print("LLM Response:")
    print(description_text)

    try:
        # Try to parse the object
        obj = description_text.split("```json")[-1].strip()
        obj = obj.split("```")[0].strip()

        return parser.parse(obj)
    except Exception:
        rprint("Failed to parse JSON from LLM response. Returning raw text.")
        traceback.print_exc()


def get_rewritten_description(description, instructions: list[str] = []):
    if len(instructions) >= 2 and instructions[1]:
        prompt = f"Rewrite these sentences:\n{description}.\n\n{instructions[1]}"
        rewritten_response: str = llm.generate_from_text(prompt)  # type: ignore
        return rewritten_response.strip()
    else:
        # If no instructions are provided, just return the description
        return description


PROMPT = """
These are photos captured from a POV camera worn by me.
Describe and classify the activity being performed in the following images into one of the predefined categories.
{categories_list}

Return with the following format:

```json
{{
    "description": "A brief description of the activity."
    "category": "Category Name",
    "confidence": "High / Medium / Low",
}}
```
"""


def describe_segment(device: str, segment: list[str], segment_idx: int, extra_info: list[str] = []):
    image_bytes = []
    if len(segment) > 20:
        segment = [segment[i] for i in sorted(random.sample(range(len(segment)), 20))]

    final_category = "Unclear"
    for image_path in segment:
        # Read webp then convert to jpeg and send bytes
        # img = open(f"{DIR}/{image_path}", "rb").read()
        # image_bytes.append(img)
        if THUMBNAIL_DIR not in image_path:
            image_path = f"{THUMBNAIL_DIR}/{device}/{image_path}"
        try:
            image = Image.open(image_path).convert("RGB")
            buf = io.BytesIO()
            image.save(buf, format="JPEG")
            image_bytes.append(buf.getvalue())
        except Exception as e:
            rprint(f"Failed to process image {image_path}. Skipping. Error: {e}")
            traceback.print_exc()

    category = "Unclear"
    description = ""
    confidence = "Low"
    tries = 0
    while True:
        if tries >= 5:
            rprint("Max retries reached. Skipping segment.")
            break
        try:
            tries += 1
            parsed_obj = get_description_from_frames(
                [
                    PROMPT.format(
                        categories_list="\n".join([f"- {c}" for c in CATEGORIES.keys()])
                    )
                ] + extra_info,
                image_bytes,
            )

            if parsed_obj:
                category = parsed_obj.get("category", "Unclear")
                description = parsed_obj.get("description", "")
                confidence = parsed_obj.get("confidence", "Low")
            break
        except KeyboardInterrupt as e:
            raise e
        except ClientError as e:
            for detail in e.details["error"]["details"]:
                if "retryDelay" in detail:
                    rprint(f"Retry after: {detail['retryDelay']}")
                    delay = detail["retryDelay"]
                    delay = int(delay.replace("s", "")) + 10
                    time.sleep(delay)
        except ServerError:
            time.sleep(10)

    possible_categories = [c for c in CATEGORIES if c.lower() in str(category).lower()]
    if possible_categories:
        final_category = possible_categories[0]

    print(f"Segment {segment_idx}: {final_category}")
    ImageRecord.update_many(
        filter={"segment_id": segment_idx, "device": device},
        data={
            "$set": {
                "activity": final_category,
                "activity_description": description,
                "activity_confidence": confidence,
            }
        },
    )
    return description

import io
import random
import time
import traceback

from celery.utils.log import get_task_logger
from constants import CATEGORIES, THUMBNAIL_DIR
from google.genai.errors import ClientError, ServerError
from llm import MixedContent, get_visual_content, llm
from partialjson.json_parser import JSONParser
from PIL import Image


logger = get_task_logger(__name__)
parser = JSONParser()


def get_description_from_frames(
    instructions: list[str], image_bytes: list[bytes]
) -> dict[str, str] | None:
    description = llm.generate_from_mixed_media(
        get_visual_content(image_bytes)
        + [
            MixedContent(type="text", content=instructions)
            for instructions in instructions
        ]
    )
    description = str(description)
    description_text = description.strip()
    logger.info(f"LLM Response:\n{description_text}")

    try:
        obj = description_text.split("```json")[-1].strip()
        obj = obj.split("```")[0].strip()
        return parser.parse(obj)
    except Exception:
        logger.warning("Failed to parse JSON from LLM response. Returning raw text.")
        logger.debug(traceback.format_exc())


def get_rewritten_description(description, instructions: list[str] = []):
    if len(instructions) >= 2 and instructions[1]:
        prompt = f"Rewrite these sentences:\n{description}.\n\n{instructions[1]}"
        rewritten_response: str = llm.generate_from_text(prompt)  # type: ignore
        return rewritten_response.strip()
    else:
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


def describe_segment(
    mongo_collection,
    device: str,
    date: str,
    segment: list[str],
    segment_id: int,
    extra_info: list[str] = [],
):
    logger.info(
        f"[{device}/{date}] Describing segment {segment_id} ({len(segment)} images)"
    )

    image_bytes = []
    if len(segment) > 20:
        segment = [segment[i] for i in sorted(random.sample(range(len(segment)), 20))]
        logger.debug(f"Segment {segment_id}: downsampled to 20 images")

    for image_path in segment:
        if THUMBNAIL_DIR not in image_path:
            image_path = f"{THUMBNAIL_DIR}/{device}/{image_path}"
        try:
            image = Image.open(image_path).convert("RGB")
            buf = io.BytesIO()
            image.save(buf, format="JPEG")
            image_bytes.append(buf.getvalue())
        except Exception as e:
            logger.warning(
                f"Segment {segment_id}: failed to load image {image_path}: {e}"
            )
            logger.debug(traceback.format_exc())

    if not image_bytes:
        logger.error(f"Segment {segment_id}: no valid images, skipping.")
        return ""

    final_category = "Unclear"
    category = "Unclear"
    description = ""
    confidence = "Low"
    tries = 0

    while True:
        if tries >= 5:
            logger.error(f"Segment {segment_id}: max retries reached, skipping.")
            break
        try:
            tries += 1
            logger.debug(f"Segment {segment_id}: LLM attempt {tries}")
            parsed_obj = get_description_from_frames(
                [
                    PROMPT.format(
                        categories_list="\n".join([f"- {c}" for c in CATEGORIES.keys()])
                    )
                ]
                + extra_info,
                image_bytes,
            )

            if parsed_obj:
                category = parsed_obj.get("category", "Unclear")
                description = parsed_obj.get("description", "")
                confidence = parsed_obj.get("confidence", "Low")
                logger.info(
                    f"Segment {segment_id}: category={category}, confidence={confidence}"
                )
            else:
                logger.warning(f"Segment {segment_id}: LLM returned no parsed object")
            break

        except KeyboardInterrupt as e:
            raise e
        except ClientError as e:
            delay = 10
            for detail in e.details["error"]["details"]:
                if "retryDelay" in detail:
                    delay = int(detail["retryDelay"].replace("s", "")) + 10
            logger.warning(
                f"Segment {segment_id}: ClientError, retrying in {delay}s: {e}"
            )
            time.sleep(delay)
        except ServerError as e:
            logger.warning(f"Segment {segment_id}: ServerError, retrying in 10s: {e}")
            time.sleep(10)

    possible_categories = [c for c in CATEGORIES if c.lower() in str(category).lower()]
    if possible_categories:
        final_category = possible_categories[0]

    logger.info(f"Segment {segment_id}: final category={final_category}")

    mongo_collection.update_one(
        {"segment_id": segment_id, "device": device, "date": date},
        {
            "$set": {
                "activity": final_category,
                "activity_description": description,
                "activity_confidence": confidence,
            }
        },
    )
    return description

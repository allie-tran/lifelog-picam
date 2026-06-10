import io
import random
import time
import traceback
import numpy as np

from celery.utils.log import get_task_logger
from constants import CATEGORIES, CATEGORIES_WITH_GROUPS, THUMBNAIL_DIR
from google.genai.errors import ClientError, ServerError
from llm import MixedContent, get_visual_content, llm
from partialjson.json_parser import JSONParser
from PIL import Image
from visual import clip_model

logger = get_task_logger(__name__)
logger.setLevel("DEBUG")
parser= JSONParser()


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


_GROUP_NAMES = list(CATEGORIES_WITH_GROUPS.keys())

PROMPT = """
These are photos captured from a POV lifelogging camera worn by me.

{context_block}
Step 1 — Pick the broad group that best matches what is happening (choose exactly one):
{groups_list}

Step 2 — Write a short activity label in gerund form (2–4 words), specific enough to be useful but consistent across similar scenes. Good examples: "writing code", "eating lunch", "commuting by train", "attending a lecture", "having a conversation", "tidying the desk".

Step 3 — Write one or two short sentences describing what is visible in the scene. Use the context above (time, location, if stationary) to understand the scene, but don't repeat them.

Return only valid JSON in this format:

```json
{{
    "group": "exact group name from the list above",
    "activity": "short gerund label",
    "description": "scene description",
    "confidence": "High / Medium / Low"
}}
```
"""


def describe_segment(
    device: str,
    date: str,
    segment: list[str],
    segment_id: int,
    context: str = "",
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
        return {
            "activity": "Unclear",
            "group": "Miscellaneous",
            "activity_description": "",
            "activity_confidence": "Low",
        }

    group = "Miscellaneous"
    activity = "unclear activity"
    description = ""
    confidence = "Low"
    tries = 0

    context_block = f"Context about this segment:\n{context}\n\n" if context else ""
    formatted_prompt = PROMPT.format(
        groups_list="\n".join(f"- {g}" for g in _GROUP_NAMES),
        context_block=context_block,
    )

    while True:
        if tries >= 5:
            logger.error(f"Segment {segment_id}: max retries reached, skipping.")
            break
        try:
            tries += 1
            logger.debug(f"Segment {segment_id}: LLM attempt {tries}")
            parsed_obj = get_description_from_frames(
                [formatted_prompt] + extra_info,
                image_bytes,
            )

            if parsed_obj:
                raw_group = parsed_obj.get("group", "")
                activity = parsed_obj.get("activity", "unclear activity").lower().strip()
                description = parsed_obj.get("description", "")
                confidence = parsed_obj.get("confidence", "Low")

                # Snap to the nearest valid group (case-insensitive substring match)
                matched = [g for g in _GROUP_NAMES if g.lower() == raw_group.lower()]
                if not matched:
                    matched = [g for g in _GROUP_NAMES if g.lower() in raw_group.lower() or raw_group.lower() in g.lower()]
                group = matched[0] if matched else "Miscellaneous"

                logger.info(
                    f"Segment {segment_id}: group={group}, activity={activity}, confidence={confidence}"
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

    return {
        "activity": activity.title(),
        "activity_group": group,
        "activity_description": description,
        "activity_confidence": confidence,
    }

class ADLClassifier:
    def __init__(self):
        self.activites = CATEGORIES
        self.adl_texts = [
            f"A POV photo showing {c.lower()}." for c in CATEGORIES
        ]
        self.loaded = False

    def load(self):
        ald_text_feats = [
            clip_model.encode_text(text) for text in self.adl_texts
        ]
        ald_text_feats = np.stack(ald_text_feats)
        self.adl_text_feats = ald_text_feats
        self.loaded = True

    def classify(self, matrix: np.ndarray | None, image_embeddings: np.ndarray):
        if not self.loaded:
            self.load()

        image_embeddings = image_embeddings / np.linalg.norm(image_embeddings, axis=1, keepdims=True)
        logger.debug(f"Classifying segment with {len(image_embeddings)} image embeddings")
        logger.debug(f"ADL text features shape: {self.adl_text_feats.shape}")
        if matrix is not None:
            adl_text_feats = self.adl_text_feats @ matrix
        else:
            adl_text_feats = self.adl_text_feats
        adl_text_feats = adl_text_feats / np.linalg.norm(adl_text_feats, axis=1, keepdims=True)
        similarities = image_embeddings @ adl_text_feats
        exp_similarities = np.exp(similarities)
        scores = exp_similarities / np.sum(exp_similarities, axis=1, keepdims=True)
        avg_scores = np.mean(scores, axis=0)
        best_idx = np.argmax(avg_scores)
        best_category = self.activites[best_idx]
        confidence = avg_scores[best_idx]
        return best_category, confidence

adl_classifier = ADLClassifier()
def simple_describe_segment(
    embeddings: list[np.ndarray],
    matrix: np.ndarray | None,
    segment_id: int,
):
    if len(embeddings) == 0:
        logger.warning(f"Segment {segment_id}: no embeddings, skipping.")
        return {
            "activity": "Unclear",
            "activity_description": "",
            "activity_confidence": "Low",
        }

    activity, confidence = adl_classifier.classify(matrix, np.stack(embeddings))
    logger.debug(f"Segment {segment_id}: classified activity='{activity}' with confidence={confidence:.4f}")
    confidence_text = ""
    if confidence < 0.1:
        activity = "Unclear Activity"
        confidence_text = "Low"
    elif confidence < 0.3:
        confidence_text = "Low"
    elif confidence < 0.6:
        confidence_text = "Medium"
    else:
        confidence_text = "High"

    return {
        "activity": activity,
        "activity_description": "",
        "activity_confidence": confidence_text,
    }

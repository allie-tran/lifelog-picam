"""Food pass — structured food detail for an eating segment.

Mirrors services/describe_segments.py but asks the vision LLM for a structured
meal record (items + rough portion, rough calories, meal type, healthiness).
Portions and calories are explicitly ballpark estimates, not medical figures.
"""
import io
import traceback

from PIL import Image

from core.config import THUMBNAIL_DIR
from integrations.llm import MixedContent, get_visual_content, llm
from partialjson.json_parser import JSONParser
from celery.utils.log import get_task_logger

logger = get_task_logger(__name__)
_parser = JSONParser()

_MEAL_TYPES = {"breakfast", "lunch", "dinner", "snack"}

# Vision cost scales with images sent. A meal segment's frames are near-duplicates
# of the same plate, so a few evenly-spaced frames are plenty — keep this small.
_MAX_IMAGES = 3

_PROMPT = """These are photos from a POV lifelogging camera worn by me during an eating moment{time_hint}.

Identify ONLY the food and drink that I (the camera wearer) am actually eating or
drinking — my own plate, cup, or what's in my hands. Estimate ROUGH, ballpark
portions and calories — approximate is fine, do not overthink.

EXCLUDE anything I'm not consuming: other people's plates and drinks, dishes merely
sitting on the table that I don't touch, untouched/background bottles, condiments and
jars unless I actually use them, menus, and decor. If you can't tell whether I'm
consuming an item, leave it out. Better to list fewer, confident items.

Return ONLY valid JSON in this exact format:

```json
{{
    "meal_type": "breakfast | lunch | dinner | snack",
    "items": [
        {{"name": "food or drink item", "portion": "rough amount e.g. 'bowl', '2 slices', 'large cup'", "calories": 0}}
    ],
    "total_calories": 0,
    "healthiness": "one short phrase, e.g. 'veg-heavy', 'balanced', 'sugary treat'",
    "summary": "one short sentence describing the meal"
}}
```

Rules: ground every item in the photos — do NOT invent. If no food/drink is clearly
visible, return an empty items list. calories/total_calories are integers (rough); use
your best guess. Pick meal_type using the time of day when given.
"""


def _sample_evenly(paths: list[str], n: int) -> list[str]:
    """Pick up to n evenly-spaced frames (a plate barely changes within a segment,
    so evenly-spaced beats sending them all)."""
    if len(paths) <= n:
        return paths
    step = (len(paths) - 1) / (n - 1) if n > 1 else 0
    return [paths[round(i * step)] for i in range(n)]


def _load_bytes(device: str, paths: list[str]) -> list[bytes]:
    paths = _sample_evenly(paths, _MAX_IMAGES)
    out: list[bytes] = []
    for p in paths:
        path = p if THUMBNAIL_DIR in p else f"{THUMBNAIL_DIR}/{device}/{p}"
        try:
            img = Image.open(path).convert("RGB")
            buf = io.BytesIO()
            img.save(buf, format="JPEG")
            out.append(buf.getvalue())
        except Exception as e:
            logger.warning("food_pass: failed to load %s: %s", path, e)
    return out


def _normalize(obj: dict) -> dict:
    """Coerce the LLM JSON into the SegmentFood shape (defensive)."""
    def _int(v):
        try:
            return int(round(float(v)))
        except (TypeError, ValueError):
            return None

    items = []
    for it in (obj.get("items") or []):
        if not isinstance(it, dict):
            continue
        name = (it.get("name") or "").strip()
        if not name:
            continue
        items.append({
            "name": name,
            "portion": (it.get("portion") or "").strip(),
            "calories": _int(it.get("calories")),
        })
    meal_type = (obj.get("meal_type") or "").strip().lower()
    if meal_type not in _MEAL_TYPES:
        meal_type = None
    return {
        "items": items,
        "meal_type": meal_type,
        "total_calories": _int(obj.get("total_calories")),
        "healthiness": (obj.get("healthiness") or "").strip() or None,
        "summary": (obj.get("summary") or "").strip() or None,
    }


def describe_food_segment(
    device: str,
    date: str,
    thumbnails: list[str],
    segment_id: int,
    local_time: str = "",
) -> dict | None:
    """Return the normalized food record for a segment, or None on failure/no food."""
    image_bytes = _load_bytes(device, thumbnails)
    if not image_bytes:
        logger.error("food_pass: segment %s has no images", segment_id)
        return None

    time_hint = f" at around {local_time}" if local_time else ""
    prompt = _PROMPT.format(time_hint=time_hint)
    try:
        raw = llm.generate_from_mixed_media(
            get_visual_content(image_bytes) + [MixedContent(type="text", content=prompt)]
        )
    except Exception as e:
        logger.warning("food_pass: LLM call failed for segment %s: %s", segment_id, e)
        logger.debug(traceback.format_exc())
        return None

    text = str(raw).strip()
    try:
        blob = text.split("```json")[-1].split("```")[0].strip() if "```" in text else text
        obj = _parser.parse(blob)
    except Exception:
        logger.warning("food_pass: could not parse JSON for segment %s", segment_id)
        return None
    if not isinstance(obj, dict):
        return None
    return _normalize(obj)

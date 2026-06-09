"""
novelty.py — identify what was unique about a given day.

Algorithm:
  For each segment on `date`, compute a novelty score with three components:

  1. CLIP novelty (W_CLIP):
       1 − max cosine-similarity(segment centroid, any historical centroid).
       Near 1.0 → nothing visually similar happened recently.

  2. Frequency novelty (W_FREQ):
       1 − (how often this activity_group appeared in history / total historical segments).
       Near 1.0 → this group is rare in the past HISTORY_DAYS days.

  3. Location novelty (W_LOCATION):
       1 − (how often this location appeared in history / total historical segments).
       Near 1.0 → person was somewhere they rarely go.

  final_novelty = W_CLIP·clip + W_FREQ·freq + W_LOCATION·location

  Top-N highest-scoring segments are sent (with images and location context)
  to the LLM to generate a human-readable day highlight.
"""
from __future__ import annotations

import io
import logging
import random
from collections import defaultdict
from datetime import datetime, timedelta
from typing import Optional

import numpy as np
from sqlalchemy import select
from sqlalchemy.orm import Session

from constants import THUMBNAIL_DIR
from database.models import Image, ImageEmbedding, Location
from llm import llm
from llm.gemini import MixedContent, get_visual_content

logger = logging.getLogger(__name__)

HISTORY_DAYS = 14
TOP_N = 3
MAX_IMAGES_PER_SEG = 4

# Novelty component weights
W_CLIP     = 0.50
W_FREQ     = 0.30
W_LOCATION = 0.20


# ---------------------------------------------------------------------------
# Historical stats (single query covers CLIP + frequency + location)
# ---------------------------------------------------------------------------

def _historical_stats(
    session: Session,
    device: str,
    date: str,
    days: int = HISTORY_DAYS,
) -> tuple[np.ndarray, dict[str, int], dict[int, int], int]:
    """
    One query over the previous `days` days.

    Returns:
      centroids       — (S, D) L2-normalised per-segment mean CLIP embeddings
      activity_counts — {activity_group: number_of_segments}
      location_counts — {location_id: number_of_segments}
      total_segments  — total distinct segments in history
    """
    date_dt = datetime.strptime(date, "%Y-%m-%d")
    cutoff = (date_dt - timedelta(days=days)).strftime("%Y-%m-%d")

    rows = session.execute(
        select(
            Image.segment_id,
            Image.date,
            Image.activity_group,
            Image.location_id,
            ImageEmbedding.embedding,
        )
        .join(ImageEmbedding, ImageEmbedding.image_id == Image.id)
        .where(
            Image.device == device,
            Image.date >= cutoff,
            Image.date < date,
            Image.deleted == False,
            Image.segment_id.isnot(None),
        )
    ).all()

    if not rows:
        return np.empty((0, 768), dtype=np.float32), {}, {}, 0

    # Group by (date, segment_id) to compute one centroid per segment
    groups: dict[tuple, dict] = {}
    for seg_id, seg_date, activity_group, location_id, emb in rows:
        key = (seg_date, seg_id)
        if key not in groups:
            groups[key] = {
                "embeddings": [],
                "activity_group": activity_group or "",
                "location_id": location_id,
            }
        groups[key]["embeddings"].append(np.array(emb, dtype=np.float32))

    centroids: list[np.ndarray] = []
    activity_counts: dict[str, int] = defaultdict(int)
    location_counts: dict[int, int] = defaultdict(int)

    for g in groups.values():
        c = np.mean(g["embeddings"], axis=0)
        norm = np.linalg.norm(c)
        if norm > 1e-8:
            centroids.append(c / norm)

        if g["activity_group"]:
            activity_counts[g["activity_group"]] += 1
        if g["location_id"] is not None:
            location_counts[g["location_id"]] += 1

    total = len(groups)
    mat = np.array(centroids, dtype=np.float32) if centroids else np.empty((0, 768), dtype=np.float32)
    return mat, dict(activity_counts), dict(location_counts), total


def _segment_centroid(
    session: Session,
    device: str,
    segment_id: int,
    date: str,
) -> Optional[np.ndarray]:
    """L2-normalised mean CLIP embedding for a segment, or None."""
    rows = session.execute(
        select(ImageEmbedding.embedding)
        .join(Image, Image.id == ImageEmbedding.image_id)
        .where(
            Image.device == device,
            Image.segment_id == segment_id,
            Image.date == date,
            Image.deleted == False,
        )
    ).scalars().all()

    if not rows:
        return None

    mat = np.array([np.array(r) for r in rows], dtype=np.float32)
    c = mat.mean(axis=0)
    norm = np.linalg.norm(c)
    return c / norm if norm > 1e-8 else None


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def compute_segment_novelty(
    session: Session,
    device: str,
    date: str,
) -> list[dict]:
    """
    Returns a list of dicts sorted by novelty score (descending):
      {segment_id, novelty, clip_novelty, freq_novelty, location_novelty,
       activity, activity_group, location_name, representative_thumbnail}
    """
    seg_rows = session.execute(
        select(Image.segment_id, Image.activity, Image.activity_group, Image.location_id)
        .where(
            Image.device == device,
            Image.date == date,
            Image.deleted == False,
            Image.segment_id.isnot(None),
        )
        .distinct(Image.segment_id)
    ).all()

    if not seg_rows:
        return []

    history, activity_counts, location_counts, total_hist = _historical_stats(
        session, device, date
    )

    # Batch-fetch location names for all location_ids seen today
    location_ids = {r.location_id for r in seg_rows if r.location_id is not None}
    loc_map: dict[int, str] = {}
    if location_ids:
        loc_rows = session.execute(
            select(Location.id, Location.name, Location.suburb, Location.city)
            .where(Location.id.in_(location_ids))
        ).all()
        for lr in loc_rows:
            loc_map[lr.id] = lr.name or lr.suburb or lr.city or ""

    results = []
    for seg_id, activity, activity_group, location_id in seg_rows:
        centroid = _segment_centroid(session, device, seg_id, date)
        if centroid is None:
            continue

        # 1. CLIP novelty
        if history.shape[0] > 0:
            clip_novelty = float(1.0 - (history @ centroid).max())
        else:
            clip_novelty = 1.0

        # 2. Frequency novelty — rare activity_groups score higher
        if total_hist > 0 and activity_group:
            freq = activity_counts.get(activity_group, 0)
            freq_novelty = 1.0 - min(freq / total_hist, 1.0)
        else:
            freq_novelty = 0.5  # no data → neutral

        # 3. Location novelty — rarely-visited locations score higher
        if total_hist > 0 and location_id is not None:
            loc_freq = location_counts.get(location_id, 0)
            location_novelty = 1.0 - min(loc_freq / total_hist, 1.0)
        else:
            location_novelty = 0.5  # unknown location → neutral

        novelty = W_CLIP * clip_novelty + W_FREQ * freq_novelty + W_LOCATION * location_novelty

        thumb = session.execute(
            select(Image.thumbnail)
            .where(
                Image.device == device,
                Image.segment_id == seg_id,
                Image.date == date,
                Image.deleted == False,
            )
            .order_by(Image.timestamp.asc())
            .limit(1)
        ).scalars().first()

        results.append({
            "segment_id": seg_id,
            "novelty": novelty,
            "clip_novelty": clip_novelty,
            "freq_novelty": freq_novelty,
            "location_novelty": location_novelty,
            "activity": activity or "Unknown",
            "activity_group": activity_group or "",
            "location_name": loc_map.get(location_id, "") if location_id else "",
            "representative_thumbnail": thumb,
        })

    results.sort(key=lambda x: x["novelty"], reverse=True)
    return results


def generate_unique_day_highlight(
    session: Session,
    device: str,
    date: str,
) -> tuple[str, list[int]]:
    """
    Compute novelty scores, then ask the LLM to describe what made the day
    unusual based on the top-N novel segments.

    Returns (highlight_text, [novel_segment_ids]).
    """
    scored = compute_segment_novelty(session, device, date)
    if not scored:
        return "", []

    top_novel = scored[:TOP_N]
    novel_ids = [s["segment_id"] for s in top_novel]

    image_bytes: list[bytes] = []
    segment_labels: list[str] = []

    for entry in top_novel:
        seg_id       = entry["segment_id"]
        activity     = entry["activity"]
        location     = entry["location_name"]
        novelty_pct  = int(entry["novelty"] * 100)
        freq_pct     = int(entry["freq_novelty"] * 100)
        loc_pct      = int(entry["location_novelty"] * 100)

        thumbs = session.execute(
            select(Image.thumbnail)
            .where(
                Image.device == device,
                Image.segment_id == seg_id,
                Image.date == date,
                Image.deleted == False,
            )
            .order_by(Image.timestamp.asc())
        ).scalars().all()

        if len(thumbs) > MAX_IMAGES_PER_SEG:
            thumbs = random.sample(list(thumbs), MAX_IMAGES_PER_SEG)

        for thumb in thumbs:
            path = f"{THUMBNAIL_DIR}/{device}/{thumb}"
            try:
                from PIL import Image as PILImage
                img = PILImage.open(path).convert("RGB")
                buf = io.BytesIO()
                img.save(buf, format="JPEG", quality=70)
                image_bytes.append(buf.getvalue())
            except Exception as e:
                logger.debug("Could not open thumbnail %s: %s", path, e)

        label = f"Activity: {activity}"
        if location:
            label += f" @ {location}"
        label += (
            f" — novelty {novelty_pct}%"
            f" (visual: {int(entry['clip_novelty']*100)}%,"
            f" rarity: {freq_pct}%,"
            f" new location: {loc_pct}%)"
        )
        segment_labels.append(label)

    activity_list = "; ".join(
        f"{s['activity']}{' at ' + s['location_name'] if s['location_name'] else ''}"
        for s in top_novel
    )

    if not image_bytes:
        try:
            text = llm.generate_from_text(
                f"On {date}, the following moments stood out as unusual compared to "
                f"the past {HISTORY_DAYS} days (considering both activity rarity and "
                f"location): {activity_list}. "
                f"In 2-3 sentences in first person, describe what made this day unique."
            )
            return str(text).strip(), novel_ids
        except Exception as e:
            logger.error("Novelty LLM (text-only) failed: %s", e)
            return "", novel_ids

    visual_contents = get_visual_content(image_bytes)
    mixed: list[MixedContent] = [
        MixedContent(
            type="text",
            content=(
                f"These images are from {date}. The moments below stood out as unusual "
                f"compared to the past {HISTORY_DAYS} days — scored by visual similarity, "
                f"activity rarity, and location novelty.\n\n"
                + "\n".join(segment_labels)
                + "\n\nIn 2-3 sentences in first person, describe what made this day "
                  "unique or different from your usual routine. Mention specific activities "
                  "and locations where relevant."
            ),
        )
    ] + visual_contents

    try:
        result = llm.generate_from_mixed_media(mixed)
        return str(result).strip(), novel_ids
    except Exception as e:
        logger.error("Novelty LLM failed: %s", e)
        return "", novel_ids

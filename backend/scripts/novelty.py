"""
novelty.py — identify what was unique about a given day.

Algorithm:
  1. For each segment on `date`, compute its CLIP centroid (mean of image
     embeddings, L2-normalised).
  2. Fetch segment centroids for the previous HISTORY_DAYS days (same device).
  3. novelty(s) = 1 − max cosine-similarity(s, any historical centroid).
     A score near 1.0 means nothing like this happened recently.
  4. Select the TOP_N most novel segments and feed their representative images
     to the LLM with a prompt asking "what made today unusual".

The result is stored in DaySummary.unique_highlight.
"""
from __future__ import annotations

import io
import logging
import random
from datetime import datetime, timedelta
from typing import Optional

import numpy as np
from sqlalchemy import select
from sqlalchemy.orm import Session

from constants import THUMBNAIL_DIR
from database.models import Image, ImageEmbedding
from llm import llm
from llm.gemini import MixedContent, get_visual_content

logger = logging.getLogger(__name__)

HISTORY_DAYS = 14
TOP_N = 3          # how many novel segments to highlight
MAX_IMAGES_PER_SEG = 4  # images sent to LLM per novel segment


# ---------------------------------------------------------------------------
# Centroid helpers
# ---------------------------------------------------------------------------
def _segment_centroid(
    session: Session,
    device: str,
    segment_id: int,
    date: str,
) -> Optional[np.ndarray]:
    """Return L2-normalised mean CLIP embedding for a segment, or None."""
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
    centroid = mat.mean(axis=0)
    norm = np.linalg.norm(centroid)
    return centroid / norm if norm > 1e-8 else None


def _historical_centroids(
    session: Session,
    device: str,
    date: str,
    days: int = HISTORY_DAYS,
) -> np.ndarray:
    """
    Return matrix of shape (S, D) containing one centroid per segment
    for the `days` days preceding `date`.  May be empty (shape (0, D)).
    """
    date_dt = datetime.strptime(date, "%Y-%m-%d")
    cutoff = (date_dt - timedelta(days=days)).strftime("%Y-%m-%d")

    # Compute per-(date, segment_id) mean embedding in one query via averaging
    rows = session.execute(
        select(
            Image.segment_id,
            Image.date,
            # pgvector supports avg() aggregate
            ImageEmbedding.embedding,
        )
        .join(Image, Image.id == ImageEmbedding.image_id)
        .where(
            Image.device == device,
            Image.date >= cutoff,
            Image.date < date,
            Image.deleted == False,
            Image.segment_id.isnot(None),
        )
    ).all()

    if not rows:
        return np.empty((0, 768), dtype=np.float32)

    # Group by (date, segment_id) and compute centroid in Python
    groups: dict[tuple, list] = {}
    for seg_id, seg_date, emb in rows:
        key = (seg_date, seg_id)
        groups.setdefault(key, []).append(np.array(emb, dtype=np.float32))

    centroids = []
    for vecs in groups.values():
        c = np.mean(vecs, axis=0)
        n = np.linalg.norm(c)
        if n > 1e-8:
            centroids.append(c / n)

    return np.array(centroids, dtype=np.float32) if centroids else np.empty((0, 768), dtype=np.float32)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------
def compute_segment_novelty(
    session: Session,
    device: str,
    date: str,
) -> list[dict]:
    """
    Returns a list of dicts sorted by novelty (descending):
      {segment_id, novelty, activity, representative_thumbnail}

    novelty = 1 - max cosine similarity to any historical segment centroid.
    A segment never seen before scores close to 1.0.
    """
    # Get today's distinct segment IDs
    seg_ids = session.execute(
        select(Image.segment_id, Image.activity)
        .where(
            Image.device == device,
            Image.date == date,
            Image.deleted == False,
            Image.segment_id.isnot(None),
        )
        .distinct(Image.segment_id)
    ).all()

    if not seg_ids:
        return []

    history = _historical_centroids(session, device, date)

    results = []
    for seg_id, activity in seg_ids:
        centroid = _segment_centroid(session, device, seg_id, date)
        if centroid is None:
            continue

        if history.shape[0] > 0:
            sims = history @ centroid   # (S,)
            novelty = float(1.0 - sims.max())
        else:
            novelty = 1.0  # no history → everything is novel

        # Pick a representative thumbnail (first image in segment)
        thumb_row = session.execute(
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
            "activity": activity or "Unknown",
            "representative_thumbnail": thumb_row,
        })

    results.sort(key=lambda x: x["novelty"], reverse=True)
    return results


def generate_unique_day_highlight(
    session: Session,
    device: str,
    date: str,
) -> tuple[str, list[int]]:
    """
    Compute novelty scores for all segments on `date`, then ask the LLM
    to describe what made the day unusual based on the top-N novel segments.

    Returns (highlight_text, [novel_segment_ids]).
    """
    scored = compute_segment_novelty(session, device, date)
    if not scored:
        return "", []

    top_novel = scored[:TOP_N]
    novel_ids = [s["segment_id"] for s in top_novel]

    # Collect images for the LLM
    image_bytes: list[bytes] = []
    segment_labels: list[str] = []

    for entry in top_novel:
        seg_id = entry["segment_id"]
        activity = entry["activity"]
        novelty_pct = int(entry["novelty"] * 100)

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

        # Down-sample to at most MAX_IMAGES_PER_SEG
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

        segment_labels.append(
            f"Segment: {activity} (novelty {novelty_pct}%)"
        )

    if not image_bytes:
        # Fallback: text-only
        activity_list = ", ".join(s["activity"] for s in top_novel)
        try:
            text = llm.generate_from_text(
                f"On {date}, the following activities were unusual compared to the past two weeks: "
                f"{activity_list}. In 2-3 sentences, describe what made this day unique."
            )
            return str(text).strip(), novel_ids
        except Exception as e:
            logger.error("Novelty LLM (text-only) failed: %s", e)
            return "", novel_ids

    # Build interleaved [label, image, label, image, ...] content
    visual_contents = get_visual_content(image_bytes)
    mixed: list[MixedContent] = [
        MixedContent(
            type="text",
            content=(
                f"These images are from {date}. The highlighted moments were unusual "
                f"compared to the past {HISTORY_DAYS} days based on visual similarity analysis.\n"
                + "\n".join(segment_labels)
                + "\n\nIn 2-3 sentences, describe in first person what made this day unique "
                  "or different from your usual routine. Focus on the novel moments."
            ),
        )
    ] + visual_contents

    try:
        result = llm.generate_from_mixed_media(mixed)
        return str(result).strip(), novel_ids
    except Exception as e:
        logger.error("Novelty LLM failed: %s", e)
        return "", novel_ids

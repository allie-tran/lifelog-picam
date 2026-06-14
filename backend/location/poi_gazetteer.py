"""
poi_gazetteer.py
----------------
Offline POI candidate lookup + visual disambiguation for stop naming, with
lazy on-demand population.

A GPS stop centroid often drifts onto the venue next door, so reverse-geocoding
the centroid (nearest wins) names the wrong place. Following VAISL (Tran et al.,
MMM 2023), we instead pull *all* nearby venues and let the stop's own photos
pick which one the lifelogger was actually inside.

Candidates live in the local ``osm_pois`` table, which fills itself: the first
stop in a grid cell triggers one Overpass fetch for that cell, cached forever
(coverage tracked in ``osm_tiles``). So Overpass only ever runs in the
background pipeline, once per visited cell, off the request path — and a failed
fetch just falls back to Nominatim and retries on the next run. No separate
import script is required.

Public API:
    nearby_pois(session, lat, lon, radius_m)              -> list[dict]
    stop_visual_vector(session, device, start_ts, end_ts) -> np.ndarray | None
    disambiguate_poi(candidates, visual_vec)             -> dict | None
"""

from __future__ import annotations

import logging
import math
import time
from datetime import datetime, timedelta, timezone

import numpy as np
import requests
from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

# ImageEmbedding is the populated CLIP/search embedding (clip_embedding table is
# empty/vestigial); both are Vector(768) in clip_model space.
from database.models import Image, ImageEmbedding, OSMPoi, OSMTile

logger = logging.getLogger(__name__)

# ─── Candidate query / disambiguation ─────────────────────────────────────────
# Search radius around the stop centroid. ~40 m covers typical GPS drift between
# adjacent storefronts without dragging in venues across the street.
DEFAULT_RADIUS_M = 40.0
MAX_CANDIDATES = 12

# VAISL θ: only let vision override the geocoder when the winning candidate's
# probability clears this (and clears the runner-up by a margin). Below it the
# scene is too ambiguous, so we fall back to the Nominatim name.
POI_CONF_THRESHOLD = 0.75
POI_CONF_MARGIN = 0.10

# ─── Lazy tile fetch (Overpass) ───────────────────────────────────────────────
TILE_GRID = 0.05            # degrees (~5.5 km) — one Overpass fetch per cell
TILE_PAD = 0.005           # degrees (~550 m) — widen bbox so edge venues aren't missed
TILE_TTL = timedelta(days=180)  # refresh an 'ok' cell only after this long

_OVERPASS_URL = "https://overpass-api.de/api/interpreter"
_OVERPASS_HEADERS = {"User-Agent": "lifelog-picam/1.0 (poi-gazetteer)"}
_OVERPASS_RATE = 2.0       # seconds between Overpass calls (politeness)
_OVERPASS_TIMEOUT = 60     # per-request, seconds
_OVERPASS_ATTEMPTS = 2     # keep short: this runs inside the pipeline
_last_overpass = 0.0

# Tags whose value names the venue's type; first present wins as the category.
_CATEGORY_KEYS = ("shop", "amenity", "tourism", "leisure", "office", "aeroway")

_OVERPASS_TMPL = """[out:json][timeout:{t}];
(
  nwr["name"]["amenity"]({s},{w},{n},{e});
  nwr["name"]["shop"]({s},{w},{n},{e});
  nwr["name"]["tourism"]({s},{w},{n},{e});
  nwr["name"]["leisure"]({s},{w},{n},{e});
  nwr["name"]["office"]({s},{w},{n},{e});
);
out center tags;"""


def _tile_of(lat: float, lon: float) -> tuple[float, float]:
    """Grid-floored (lat, lon) cell key."""
    return (math.floor(lat / TILE_GRID) * TILE_GRID,
            math.floor(lon / TILE_GRID) * TILE_GRID)


def _element_to_row(el: dict) -> dict | None:
    """Map an Overpass element to an osm_pois row, or None to skip."""
    tags = el.get("tags", {})
    name = tags.get("name")
    if not name:
        return None
    if el["type"] == "node":
        lat, lon = el.get("lat"), el.get("lon")
    else:  # way / relation → 'center'
        c = el.get("center", {})
        lat, lon = c.get("lat"), c.get("lon")
    if lat is None or lon is None:
        return None
    category = next((tags[k] for k in _CATEGORY_KEYS if tags.get(k)), None)
    return {
        "osm_type": el["type"],
        "osm_id": str(el["id"]),
        "name": name,
        "category": category,
        "wikidata_id": tags.get("wikidata"),
        "latitude": float(lat),
        "longitude": float(lon),
        "geog": func.ST_SetSRID(func.ST_MakePoint(float(lon), float(lat)), 4326),
    }


def _fetch_overpass(tlat: float, tlon: float) -> list[dict] | None:
    """Overpass query for a tile bbox with short backoff. None on give-up."""
    global _last_overpass
    s, w = tlat - TILE_PAD, tlon - TILE_PAD
    n, e = tlat + TILE_GRID + TILE_PAD, tlon + TILE_GRID + TILE_PAD
    query = _OVERPASS_TMPL.format(t=_OVERPASS_TIMEOUT, s=s, w=w, n=n, e=e)
    delay = 3.0
    for i in range(_OVERPASS_ATTEMPTS):
        wait = _OVERPASS_RATE - (time.monotonic() - _last_overpass)
        if wait > 0:
            time.sleep(wait)
        try:
            r = requests.post(_OVERPASS_URL, data={"data": query},
                              headers=_OVERPASS_HEADERS, timeout=_OVERPASS_TIMEOUT + 60)
            _last_overpass = time.monotonic()
            if r.status_code == 200:
                return r.json().get("elements", [])
            logger.warning("Overpass HTTP %s for tile (%.3f,%.3f) try %d",
                           r.status_code, tlat, tlon, i + 1)
        except Exception as exc:
            _last_overpass = time.monotonic()
            logger.warning("Overpass error for tile (%.3f,%.3f) try %d: %s",
                           tlat, tlon, i + 1, exc)
        time.sleep(delay)
        delay *= 2
    return None


def _ensure_tile(session: Session, lat: float, lon: float) -> None:
    """
    Make sure the grid cell containing (lat, lon) has been fetched into
    ``osm_pois``. No-op when already cached and fresh. Records the attempt in
    ``osm_tiles`` so a stop never triggers more than one Overpass call per cell
    (failures are retried next run).
    """
    tlat, tlon = _tile_of(lat, lon)
    existing = session.get(OSMTile, (tlat, tlon))
    if existing and existing.status == "ok":
        age = datetime.now(timezone.utc) - existing.fetched_at
        if age < TILE_TTL:
            return  # cached and fresh

    elements = _fetch_overpass(tlat, tlon)
    status = "ok" if elements is not None else "failed"
    if elements:
        rows = {}
        for el in elements:
            row = _element_to_row(el)
            if row:
                rows[(row["osm_type"], row["osm_id"])] = row
        if rows:
            stmt = insert(OSMPoi).values(list(rows.values()))
            stmt = stmt.on_conflict_do_update(
                constraint="uq_osm_pois_element",
                set_={
                    "name": stmt.excluded.name,
                    "category": stmt.excluded.category,
                    "wikidata_id": stmt.excluded.wikidata_id,
                    "latitude": stmt.excluded.latitude,
                    "longitude": stmt.excluded.longitude,
                    "geog": stmt.excluded.geog,
                },
            )
            session.execute(stmt)
        logger.info("Fetched %d POIs for tile (%.3f,%.3f)", len(rows), tlat, tlon)

    tile_stmt = insert(OSMTile).values(
        tile_lat=tlat, tile_lon=tlon,
        fetched_at=datetime.now(timezone.utc), status=status,
    ).on_conflict_do_update(
        index_elements=["tile_lat", "tile_lon"],
        set_={"fetched_at": datetime.now(timezone.utc), "status": status},
    )
    session.execute(tile_stmt)
    session.commit()


def nearby_pois(session: Session, lat: float, lon: float,
                radius_m: float = DEFAULT_RADIUS_M) -> list[dict]:
    """
    Named OSM venues within ``radius_m`` of (lat, lon), nearest first. Lazily
    fetches the surrounding grid cell from Overpass on first visit.
    """
    try:
        _ensure_tile(session, lat, lon)
    except Exception as exc:  # never let POI population break enrichment
        session.rollback()
        logger.warning("Tile fetch failed at (%.5f, %.5f): %s", lat, lon, exc)

    point = func.ST_SetSRID(func.ST_MakePoint(lon, lat), 4326)  # geography(POINT)
    dist = func.ST_Distance(OSMPoi.geog, point)
    try:
        rows = session.execute(
            select(OSMPoi, dist.label("d"))
            .where(func.ST_DWithin(OSMPoi.geog, point, radius_m))
            .order_by(dist)
            .limit(MAX_CANDIDATES)
        ).all()
    except Exception as exc:  # table missing / PostGIS error
        logger.warning("nearby_pois query failed at (%.5f, %.5f): %s", lat, lon, exc)
        return []
    return [
        {
            "name": p.name,
            "category": p.category or "",
            "wikidata_id": p.wikidata_id or "",
            "osm_type": p.osm_type,
            "osm_id": p.osm_id,
            "latitude": p.latitude,
            "longitude": p.longitude,
            "distance_m": float(d),
        }
        for p, d in rows
    ]


def stop_visual_vector(session: Session, device: str, start_ts, end_ts) -> np.ndarray | None:
    """
    Mean CLIP vector over the images captured during a stop's time window.
    Returns None when the stop has no embedded images.
    """
    if start_ts is None or end_ts is None:
        return None
    start_dt = start_ts.to_pydatetime() if hasattr(start_ts, "to_pydatetime") else start_ts
    end_dt = end_ts.to_pydatetime() if hasattr(end_ts, "to_pydatetime") else end_ts
    try:
        rows = session.execute(
            select(ImageEmbedding.embedding)
            .join(Image, Image.id == ImageEmbedding.image_id)
            .where(Image.device == device)
            .where(Image.timestamp.between(start_dt, end_dt))
        ).scalars().all()
    except Exception as exc:
        logger.warning("stop_visual_vector query failed: %s", exc)
        return None
    if not rows:
        return None
    feats = np.asarray([np.asarray(r, dtype=np.float32) for r in rows], dtype=np.float32)
    return feats.mean(axis=0)


def disambiguate_poi(candidates: list[dict], visual_vec: np.ndarray | None) -> dict | None:
    """
    Pick the candidate venue that best matches the stop's visual vector.

    Builds "I am in a {category} called {name}" per candidate and scores them
    against ``visual_vec`` with the shared CLIP zero-shot classifier. Returns the
    winner only when it clears POI_CONF_THRESHOLD *and* beats the runner-up by
    POI_CONF_MARGIN — otherwise None (caller falls back to the geocoder name).
    """
    if not candidates or visual_vec is None:
        return None
    descs = [
        f"{c['category']} called {c['name']}" if c.get("category") else c["name"]
        for c in candidates
    ]
    try:
        from services.clip_classifier import ClipPromptClassifier
        clf = ClipPromptClassifier(descs, prompt_templates=["I am in a {}"])
        probs = clf.predict_proba_from_features(
            np.asarray(visual_vec, dtype=np.float32)[None, :]
        )[0]
    except Exception as exc:  # model unavailable / dim mismatch
        logger.warning("POI visual disambiguation failed: %s", exc)
        return None

    order = probs.argsort()[::-1]
    top = int(order[0])
    runner = probs[order[1]] if len(order) > 1 else 0.0
    if probs[top] < POI_CONF_THRESHOLD or (probs[top] - runner) < POI_CONF_MARGIN:
        return None
    chosen = candidates[top]
    logger.info(
        "Visual POI pick: %r (p=%.2f, %d candidates, %.0fm from centroid)",
        chosen["name"], probs[top], len(candidates), chosen.get("distance_m", -1),
    )
    return chosen

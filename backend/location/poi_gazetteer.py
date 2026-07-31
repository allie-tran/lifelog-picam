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
from location.transport_mode import _haversine_m
from sqlalchemy.orm import Session

# ImageEmbedding is the populated CLIP/search embedding (clip_embedding table is
# empty/vestigial); both are Vector(768) in clip_model space.
from database.models import Image, ImageEmbedding, OSMPoi, OSMTile
from integrations.llm import llm

logger = logging.getLogger(__name__)

# ─── Candidate query / disambiguation ─────────────────────────────────────────
# Search radius around the stop centroid. ~40 m covers typical GPS drift between
# adjacent storefronts without dragging in venues across the street.
DEFAULT_RADIUS_M = 40.0
MAX_CANDIDATES = 12

# Only let the LLM override the geocoder name when it is at least this confident
# the activities point to a specific candidate. Below it the scene is ambiguous,
# so we keep the Nominatim name.
POI_LLM_CONF_THRESHOLD = 0.6

# Activity labels that carry no venue signal — skipped so a generic "no activity"
# or transit run doesn't dilute the real cues handed to the disambiguator.
_SKIP_ACTIVITIES = {"no activity", "unclear", "unclear activity", "", "walking through lobby"}

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


def _run_overpass(query: str, ctx: str) -> list[dict] | None:
    """POST an Overpass query with rate-limit + short backoff. None on give-up.
    ``ctx`` is a short label for logs (e.g. the tile/point being fetched)."""
    global _last_overpass
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
            logger.warning("Overpass HTTP %s for %s try %d", r.status_code, ctx, i + 1)
        except Exception as exc:
            _last_overpass = time.monotonic()
            logger.warning("Overpass error for %s try %d: %s", ctx, i + 1, exc)
        time.sleep(delay)
        delay *= 2
    return None


def _fetch_overpass(tlat: float, tlon: float) -> list[dict] | None:
    """Overpass query for a tile bbox with short backoff. None on give-up."""
    s, w = tlat - TILE_PAD, tlon - TILE_PAD
    n, e = tlat + TILE_GRID + TILE_PAD, tlon + TILE_GRID + TILE_PAD
    query = _OVERPASS_TMPL.format(t=_OVERPASS_TIMEOUT, s=s, w=w, n=n, e=e)
    return _run_overpass(query, f"tile ({tlat:.3f},{tlon:.3f})")


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


# ─── Transit venues (gated) ───────────────────────────────────────────────────
# Public-transport stops (stations, tram/bus stops, airport terminals) are NOT in
# the general gazetteer (nearby_pois only fetches amenity/shop/tourism/leisure/
# office) — including them everywhere would flood normal stops with roadside
# bus-stop nodes. Instead the pipeline calls this ONLY for a stop that the
# neighbour-mode gate flags as a transit waypoint (a stationary stop bracketed by
# a vehicle/flight leg). Results are kept out of osm_pois so the general candidate
# pool stays clean; a small in-process TTL cache avoids re-hitting Overpass when
# the same day reprocesses.
_TRANSIT_RADIUS_M = 250.0
_TRANSIT_TTL_S = 6 * 3600
_transit_cache: dict[tuple, tuple[float, list[dict]]] = {}

_TRANSIT_TMPL = """[out:json][timeout:{t}];
(
  nwr["name"]["railway"~"^(station|halt|tram_stop|subway_entrance)$"](around:{r},{lat},{lon});
  nwr["name"]["public_transport"~"^(station|stop_position)$"](around:{r},{lat},{lon});
  nwr["name"]["highway"="bus_stop"](around:{r},{lat},{lon});
  nwr["name"]["amenity"="bus_station"](around:{r},{lat},{lon});
  nwr["name"]["aeroway"~"^(aerodrome|terminal)$"](around:{r},{lat},{lon});
);
out center tags;"""

# Which tag names a transit venue's type; first present wins as the category.
_TRANSIT_CATEGORY_KEYS = ("railway", "public_transport", "highway", "aeroway", "amenity")


def _fetch_transit_overpass(lat: float, lon: float) -> list[dict] | None:
    """Overpass 'around' query for named transit venues near a point. None on give-up."""
    query = _TRANSIT_TMPL.format(t=_OVERPASS_TIMEOUT, r=int(_TRANSIT_RADIUS_M), lat=lat, lon=lon)
    return _run_overpass(query, f"transit ({lat:.5f},{lon:.5f})")


def nearby_transit_pois(lat: float, lon: float) -> list[dict]:
    """Named public-transport venues within ~150 m of (lat, lon), nearest first.

    Same dict shape as ``nearby_pois`` so callers can merge the two candidate
    lists. Best-effort: returns [] on any Overpass failure. Gated by the caller —
    only meant to run for stops the neighbour-mode gate marks as transit.
    """
    key = (round(lat, 3), round(lon, 3))
    hit = _transit_cache.get(key)
    if hit and (time.monotonic() - hit[0]) < _TRANSIT_TTL_S:
        return hit[1]

    elements = _fetch_transit_overpass(lat, lon)
    if elements is None:
        return []  # don't cache a failure — retry next run

    out: list[dict] = []
    for el in elements:
        tags = el.get("tags", {})
        name = tags.get("name")
        if not name:
            continue
        if el["type"] == "node":
            elat, elon = el.get("lat"), el.get("lon")
        else:
            c = el.get("center", {})
            elat, elon = c.get("lat"), c.get("lon")
        if elat is None or elon is None:
            continue
        category = next((tags[k] for k in _TRANSIT_CATEGORY_KEYS if tags.get(k)), None)
        out.append({
            "name": name,
            "category": category,
            "wikidata_id": tags.get("wikidata") or "",
            "osm_type": el["type"],
            "osm_id": str(el["id"]),
            "latitude": float(elat),
            "longitude": float(elon),
            "distance_m": _haversine_m(lat, lon, float(elat), float(elon)),
        })

    # A station explodes into dozens of near-identical platform/stop_position nodes
    # sharing one name. Collapse by name, keeping the best-typed, nearest node, so
    # the disambiguator (and the correction list) see one "Basel SBB", not seven.
    def _rank(cat: str | None) -> int:
        c = (cat or "").lower()
        if c in ("station", "aerodrome", "bus_station"):
            return 0
        if c in ("halt", "tram_stop", "terminal"):
            return 1
        return 2  # stop / stop_position / platform / subway_entrance

    best: dict[str, dict] = {}
    for c in out:
        prev = best.get(c["name"])
        key_c = (_rank(c["category"]), c["distance_m"])
        if prev is None or key_c < (_rank(prev["category"]), prev["distance_m"]):
            best[c["name"]] = c
    deduped = sorted(best.values(), key=lambda c: c["distance_m"])
    _transit_cache[key] = (time.monotonic(), deduped)
    return deduped


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


def stop_activity_labels(session: Session, device: str, start_ts, end_ts) -> list[tuple[str, int]]:
    """
    Dominant activity annotations for a stop, as (label, frame_count) pairs,
    most frequent first.

    The LLM activity layer already describes what the lifelogger was *doing*
    ("watching a movie", "exercising at gym"). That behaviour — not the drifted
    GPS point — is what separates co-located venues (a cinema above a gym), so we
    hand these labels to the disambiguator. Returns [] when the stop has no
    meaningful labels.
    """
    if start_ts is None or end_ts is None:
        return []
    start_dt = start_ts.to_pydatetime() if hasattr(start_ts, "to_pydatetime") else start_ts
    end_dt = end_ts.to_pydatetime() if hasattr(end_ts, "to_pydatetime") else end_ts
    try:
        rows = session.execute(
            select(Image.activity, func.count().label("n"))
            .where(Image.device == device)
            .where(Image.timestamp.between(start_dt, end_dt))
            .where(Image.activity.isnot(None))
            .group_by(Image.activity)
        ).all()
    except Exception as exc:
        logger.warning("stop_activity_labels query failed: %s", exc)
        return []
    labels = [
        (str(a).strip(), int(n)) for a, n in rows
        if a and str(a).strip().lower() not in _SKIP_ACTIVITIES
    ]
    labels.sort(key=lambda x: x[1], reverse=True)
    return labels


def disambiguate_poi(
    candidates: list[dict],
    activity_labels: list[tuple[str, int]],
) -> dict | None:
    """
    Pick which nearby venue a stop was actually inside, using the LLM.

    A 2-D GPS fix can't separate stacked/adjacent units (a cinema above a gym),
    and CLIP zero-shot on the mean image vector is too weak to tell them apart —
    so we reason over the stop's *activity annotations* instead. The LLM is given
    the ranked candidate venues (name, category, distance) and the observed
    activities (with frame counts) and returns the best-matching venue, or null
    when genuinely ambiguous. This runs on the annotation LLM (an API call), so
    it needs no local GPU. Returns the chosen candidate dict, or None to defer to
    the geocoder name.
    """
    if not candidates or not activity_labels:
        return None

    cand_lines = "\n".join(
        f"{i + 1}. {c['name']}"
        f" ({c.get('category') or 'unknown type'}, ~{c.get('distance_m', 0):.0f} m from GPS)"
        for i, c in enumerate(candidates)
    )
    act_lines = "\n".join(f"- {label} (seen in {n} photos)" for label, n in activity_labels)
    prompt = (
        "A lifelogger stopped at one place. GPS is only accurate to a few metres "
        "and cannot tell apart venues that are stacked on different floors or right "
        "next to each other, so trust what the person was DOING over raw GPS distance.\n\n"
        f"Nearby candidate venues (nearest first):\n{cand_lines}\n\n"
        f"Activities observed during the stop (from their photos):\n{act_lines}\n\n"
        "Which single venue were they most likely inside? Weigh the activities "
        "heavily: e.g. watching a movie => a cinema, exercising => a gym, eating => "
        "a restaurant. If the activities don't clearly point to any listed venue, "
        "return null.\n\n"
        'Respond with ONLY JSON: {"index": <1-based number of the chosen venue, or '
        'null>, "confidence": <0.0-1.0>, "reason": "<short>"}'
    )

    try:
        result = llm.generate_from_text(prompt, parse_json=True)
    except Exception as exc:
        logger.warning("LLM POI disambiguation failed: %s", exc)
        return None
    if not isinstance(result, dict):
        return None

    idx = result.get("index")
    conf = result.get("confidence", 0.0)
    try:
        conf = float(conf)
    except (TypeError, ValueError):
        conf = 0.0
    if idx is None or not isinstance(idx, (int, float)):
        return None
    idx = int(idx) - 1  # 1-based → 0-based
    if idx < 0 or idx >= len(candidates) or conf < POI_LLM_CONF_THRESHOLD:
        return None

    chosen = candidates[idx]
    logger.info(
        "LLM POI pick: %r (conf=%.2f, %d candidates, %.0fm from centroid) — %s",
        chosen["name"], conf, len(candidates), chosen.get("distance_m", -1),
        result.get("reason", ""),
    )
    return chosen

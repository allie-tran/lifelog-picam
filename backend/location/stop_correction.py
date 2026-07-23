"""Correct which venue a stop resolved to, from a user-supplied name.

When the chat assistant is told "that place was actually X", we don't want a
cosmetic per-user label — we want to fix the *stop's identity*. This matches the
name against the same offline OSM POI candidates the visual disambiguator uses
(see ``poi_gazetteer``); if one matches, the stop adopts that venue (name +
OSM/Wikidata provenance). If nothing matches, we mint an authoritative manual
venue at the stop coords. Either way the day's images for that stop are
reassigned, so location-visits, events grounding and the summary all follow.
"""
import logging
import uuid
from difflib import SequenceMatcher
from typing import Optional

from sqlalchemy import select, update
from sqlalchemy.dialects.postgresql import insert

from database.models import Image, ImageGPS, Location
from location import poi_gazetteer as pgaz
from location.enrich_stops import _poi_only_geo
from location.utils import find_timezone

logger = logging.getLogger(__name__)

# Minimum fuzzy similarity for a user name to be considered "the same place" as a
# nearby POI candidate. Substring containment always wins regardless.
_MATCH_THRESHOLD = 0.6


def _norm(s: str) -> str:
    return "".join(ch for ch in s.lower() if ch.isalnum() or ch.isspace()).strip()


def _best_candidate(name: str, candidates: list[dict]) -> Optional[dict]:
    """Pick the nearby POI whose name best matches ``name`` (substring or fuzzy)."""
    target = _norm(name)
    if not target:
        return None
    best, best_score = None, 0.0
    for c in candidates:
        cand = _norm(c.get("name") or "")
        if not cand:
            continue
        if target in cand or cand in target:
            return c
        score = SequenceMatcher(None, target, cand).ratio()
        if score > best_score:
            best, best_score = c, score
    return best if best_score >= _MATCH_THRESHOLD else None


def correct_stop_venue(
    session, device: str, date: str, segment_id: int, name: str
) -> tuple[bool, str]:
    """Re-resolve one stop's venue to ``name``. Returns (changed, message)."""
    rows = session.execute(
        select(Image.timestamp, Image.location_id, ImageGPS.latitude, ImageGPS.longitude)
        .join(ImageGPS, ImageGPS.image_id == Image.id)
        .where(
            Image.device == device,
            Image.date == date,
            Image.segment_id == segment_id,
            Image.deleted == False,
        )
    ).all()
    if not rows:
        return False, f"Segment {segment_id} has no located images to correct."

    lats = [r.latitude for r in rows if r.latitude is not None]
    lons = [r.longitude for r in rows if r.longitude is not None]
    if not lats or not lons:
        return False, f"Segment {segment_id} has no GPS to place the venue."
    lat, lon = sum(lats) / len(lats), sum(lons) / len(lons)
    old_location_id = next((r.location_id for r in rows if r.location_id is not None), None)

    # Match against the offline gazetteer candidates near the stop.
    try:
        candidates = pgaz.nearby_pois(session, lat, lon)
    except Exception:
        logger.exception("nearby_pois failed during stop correction")
        candidates = []
    chosen = _best_candidate(name, candidates)

    # Inherit the admin hierarchy from the stop's current Location (city/country
    # etc.) so we don't need a Nominatim round-trip here.
    prev = session.get(Location, old_location_id) if old_location_id else None

    if chosen:
        geo = _poi_only_geo(chosen)
        geo["name"] = chosen.get("name") or name
        raw_key = (
            f"osm_{geo['osm_type']}{geo['osm_id']}" if geo.get("osm_id")
            else f"wikidata_{geo['wikidata_id']}" if geo.get("wikidata_id")
            else f"manual_{lat:.5f}_{lon:.5f}"
        )
        matched_note = f"matched nearby '{chosen.get('name')}'"
    else:
        # No candidate matched — mint an authoritative manual venue at the stop.
        geo = {
            "name": name, "wikidata_id": "", "osm_type": "", "osm_id": "",
            "categories": [],
        }
        raw_key = f"manual_{lat:.5f}_{lon:.5f}"
        matched_note = "no nearby match — saved as a manual venue"

    key = f"stop=True,{raw_key}"
    tz = find_timezone(float(lon), float(lat))
    cats = geo.get("categories") or []
    categories_str = "; ".join(cats[:5]) if cats else None

    stmt = insert(Location).values(
        id=uuid.uuid4(),
        key=key,
        name=geo["name"],
        stop=True,
        suburb=(prev.suburb if prev else None),
        city=(prev.city if prev else None),
        region=(prev.region if prev else None),
        country=(prev.country if prev else ""),
        postcode=(prev.postcode if prev else None),
        address=(prev.address if prev else geo["name"]),
        timezone=tz,
        latitude=float(lat),
        longitude=float(lon),
        osm_type=geo.get("osm_type") or None,
        osm_id=geo.get("osm_id") or None,
        wikidata_id=geo.get("wikidata_id") or None,
        categories=categories_str,
    )
    stmt = stmt.on_conflict_do_update(
        index_elements=["key"],
        set_={
            "name": stmt.excluded.name,
            "latitude": stmt.excluded.latitude,
            "longitude": stmt.excluded.longitude,
            "timezone": stmt.excluded.timezone,
            "osm_type": stmt.excluded.osm_type,
            "osm_id": stmt.excluded.osm_id,
            "wikidata_id": stmt.excluded.wikidata_id,
            "categories": stmt.excluded.categories,
        },
    ).returning(Location.id)
    new_location_id = session.execute(stmt).scalar()
    session.flush()

    # Reassign the whole stop on this day: every image that shared the old
    # Location (so a revisited-place visit moves as one), else just this segment.
    upd = update(Image).where(Image.device == device, Image.date == date)
    if old_location_id is not None:
        upd = upd.where(Image.location_id == old_location_id)
    else:
        upd = upd.where(Image.segment_id == segment_id)
    result = session.execute(upd.values(location_id=new_location_id))
    session.commit()

    n = getattr(result, "rowcount", 0) or 0
    return True, f"Set the stop to '{geo['name']}' ({matched_note}); updated {n} images."

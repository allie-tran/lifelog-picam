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

from sqlalchemy import func, select, update
from sqlalchemy.dialects.postgresql import insert

from database.models import Image, ImageGPS, Location
from location import poi_gazetteer as pgaz
from location.enrich_stops import _poi_only_geo
from location.utils import find_timezone

logger = logging.getLogger(__name__)


def _cascade_rename(session, device: str, date: str, old_name: str, new_name: str) -> int:
    """Propagate a stop rename (old_name → new_name) through everything else on the
    day that referenced the old name:

      - **Adjacent move segments** — a trip Location is named from its endpoints
        ("A → X", "From X", "To X"), so correcting the stop X to Y must turn
        A → X → B into A → Y → B. Rewrites the name of every move Location assigned
        to this day's images that mentions the old name.
      - **Activity descriptions** — per-image text that named the place.

    Both are done with an in-place ``replace()`` on the stored strings (exact case —
    the move names/descriptions were built from the same stop name). Returns the
    number of rows touched. Caller invalidates the day summary so location-visits
    (and the day text) regenerate with the corrected name.
    """
    if not old_name or not new_name or old_name == new_name:
        return 0
    touched = 0

    # Adjacent / related move segments: rename any move Location referenced this day
    # whose name embeds the old stop name. (A move Location can be shared across days
    # for the same route; renaming it everywhere is correct — it is the same place.)
    move_ids = session.execute(
        select(Location.id)
        .join(Image, Image.location_id == Location.id)
        .where(
            Image.device == device, Image.date == date, Image.deleted == False,
            Location.stop.is_(False),
            Location.name.ilike(f"%{old_name}%"),
        ).distinct()
    ).scalars().all()
    if move_ids:
        res = session.execute(
            update(Location)
            .where(Location.id.in_(move_ids))
            .values(
                name=func.replace(Location.name, old_name, new_name),
                address=func.replace(func.coalesce(Location.address, ""), old_name, new_name),
            )
        )
        touched += getattr(res, "rowcount", 0) or 0

    # Activity descriptions that named the place.
    res = session.execute(
        update(Image)
        .where(
            Image.device == device, Image.date == date, Image.deleted == False,
            Image.activity_description.ilike(f"%{old_name}%"),
        )
        .values(activity_description=func.replace(Image.activity_description, old_name, new_name))
    )
    touched += getattr(res, "rowcount", 0) or 0
    return touched

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
    session, device: str, date: str, segment_ids, name: str,
    osm_type: Optional[str] = None, osm_id=None, whole_location: bool = False,
) -> tuple[bool, str]:
    """Re-resolve one or more stop segments' venue to ``name``. Returns (changed, message).

    ``segment_ids`` — the segment(s) to correct (a single int is accepted for
    backwards compatibility with the chat path). ``osm_type``/``osm_id`` pin the
    exact nearby POI the user picked from the list, bypassing fuzzy name matching.

    Scope of reassignment:
      * ``whole_location=False`` (default, DayNav manual correction) — reassign
        ONLY the given segments, so revisits to the same place elsewhere in the
        day (and any surrounding stop the geocoder happened to merge) are left
        untouched. This is what stops the "overcorrects the neighbours" problem.
      * ``whole_location=True`` (chat legacy) — reassign every image that shared
        the old Location on this day, so a revisited place moves as one.
    """
    if isinstance(segment_ids, int):
        segment_ids = [segment_ids]
    segment_ids = [int(s) for s in segment_ids]
    rows = session.execute(
        select(Image.timestamp, Image.location_id, ImageGPS.latitude, ImageGPS.longitude)
        .join(ImageGPS, ImageGPS.image_id == Image.id)
        .where(
            Image.device == device,
            Image.date == date,
            Image.segment_id.in_(segment_ids),
            Image.deleted == False,
        )
    ).all()
    if not rows:
        return False, f"Segment(s) {segment_ids} have no located images to correct."

    lats = [r.latitude for r in rows if r.latitude is not None]
    lons = [r.longitude for r in rows if r.longitude is not None]
    if not lats or not lons:
        return False, f"Segment(s) {segment_ids} have no GPS to place the venue."
    lat, lon = sum(lats) / len(lats), sum(lons) / len(lons)
    old_location_id = next((r.location_id for r in rows if r.location_id is not None), None)

    # Match against the offline gazetteer candidates near the stop.
    try:
        candidates = pgaz.nearby_pois(session, lat, lon)
    except Exception:
        logger.exception("nearby_pois failed during stop correction")
        candidates = []
    # An explicit POI pick (osm_type/osm_id from the DayNav list) wins over fuzzy
    # name matching — the user chose that exact venue.
    chosen = None
    if osm_type and osm_id is not None:
        chosen = next(
            (c for c in candidates
             if c.get("osm_type") == osm_type and str(c.get("osm_id")) == str(osm_id)),
            None,
        )
    if chosen is None:
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
        user_confirmed=True,
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
            "user_confirmed": True,
        },
    ).returning(Location.id)
    new_location_id = session.execute(stmt).scalar()
    session.flush()

    # Reassign scope. Default (manual DayNav correction): only the given
    # segments, so surrounding/revisited stops are left alone. Legacy chat path
    # (whole_location=True): every image that shared the old Location that day.
    upd = update(Image).where(Image.device == device, Image.date == date)
    if whole_location and old_location_id is not None:
        upd = upd.where(Image.location_id == old_location_id)
    else:
        upd = upd.where(Image.segment_id.in_(segment_ids))
    result = session.execute(upd.values(location_id=new_location_id))

    # Cascade the rename through adjacent move segments (A → X → B ⇒ A → Y → B) and
    # activity descriptions that named the place, then invalidate the day summary so
    # location-visits and the day text regenerate with the corrected name.
    old_name = prev.name if prev else None
    cascaded = 0
    if old_name and old_name != geo["name"]:
        try:
            cascaded = _cascade_rename(session, device, date, old_name, geo["name"])
        except Exception:
            logger.exception("cascade rename failed during stop correction")
    session.commit()

    if old_name and old_name != geo["name"]:
        try:
            from database.types import DaySummaryRecord
            from integrations.sessions.redis import bust_day_caches
            DaySummaryRecord.update_one(
                {"date": date, "device": device},
                data={"$set": {"updated": True, "text_summary_stale": True}},
                upsert=True,
            )
            bust_day_caches(device, date)
        except Exception:
            logger.exception("day-summary invalidation failed during stop correction")

    n = getattr(result, "rowcount", 0) or 0
    extra = f"; cascaded {cascaded} move/description mentions" if cascaded else ""
    return True, f"Set the stop to '{geo['name']}' ({matched_note}); updated {n} images{extra}."

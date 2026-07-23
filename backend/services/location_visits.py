"""
Location-visit layer for the day summary.

A *visit* is a maximal run of consecutive segments that share the same
location — i.e. one stop at one place, or one continuous stretch of transit.
This is coarser than the per-segment (~10-minute) descriptions: instead of
describing every slice, we describe each *place* the day passed through.

For notable public venues (a stop with a real POI name that is not a
personal Home/Work label) we optionally ground the description with a
Google-search lookup of current events near that place on that date, so a
description can say "watched the match at Croke Park" rather than just
"at a stadium".
"""

import json
import logging
from datetime import timedelta
from typing import Optional

from partialjson.json_parser import JSONParser
from sqlalchemy import select
from sqlalchemy.orm import Session

from database.models import Image, ImageGPS, ImagePerson, LocationLabel
from integrations.llm import llm

_json_parser = JSONParser()

logger = logging.getLogger(__name__)

# Split into a new visit when the recording gap between two same-location
# segments exceeds this — a long absence means it's really a separate visit.
_VISIT_GAP = timedelta(minutes=90)

# Activity groups/labels that never carry meaningful scene content.
_SKIP_ACTIVITIES = {"no activity", "unclear", "unclear activity", ""}

# Location names that are personal/routine — never worth an events lookup.
_PERSONAL_NAMES = {"home", "work", "house", "office", "my home", "my house"}

# Generic placeholders that mean "no real place name".
_GENERIC_NAMES = {"", "---", "unknown place", "unknown"}

# Two consecutive segments are the same visit if their centroids fall within
# this radius of the visit's spatial anchor — even when their POI names differ
# (one venue often resolves to several nearby POIs, e.g. an amphitheatre named
# after the courtyard, the org, and a nearby bar). Compared against the anchor
# (first geolocated segment of the visit), not a running mean, so the visit's
# extent stays bounded and a real walk across town still starts a new visit.
_MERGE_RADIUS_M = 200.0

# A moving segment (stop=False) longer than this is real transit (a tram/drive)
# and always breaks the visit, regardless of proximity. Shorter moves are
# treated as in-venue walking and may be absorbed if they stay within radius.
_MOVE_ABSORB_MAX_S = 10 * 60

# Only look up current events for visits that lasted at least this long — a real
# outing (concert, match, exhibition), not a tram platform passed through.
_EVENT_MIN_STOP_S = 20 * 60

# Activity-group keywords that, on their own, mean the person was NOT attending a
# public event even while inside a notable venue — they were working, in a meeting,
# or sleeping/resting there. Being at a stadium's coordinates while heads-down at a
# laptop is presence, not attendance. Matched as case-insensitive substrings so the
# check is robust to the exact group punctuation ("Work – Research & Writing").
_NON_EVENT_GROUP_KEYWORDS = ("work", "meeting", "sleep", "downtime")


def _attendance_plausible(activity_groups: list[str]) -> bool:
    """False when *every* activity group in the visit is non-attending (work /
    meeting / sleep) — then skip event grounding. Unknown (no groups) → True, so we
    don't suppress on missing annotations."""
    if not activity_groups:
        return True
    return not all(
        any(k in g.lower() for k in _NON_EVENT_GROUP_KEYWORDS) for g in activity_groups
    )

# A stationary stop no longer than this, when sandwiched by transit, is treated
# as a transit waypoint (waiting at a platform/stop) and folded into the journey
# rather than shown as its own visit. Longer stops are real destinations.
_WAIT_MAX_S = 3 * 60


def _norm(name: Optional[str]) -> str:
    return (name or "").strip().lower()


def _haversine_m(lat1, lon1, lat2, lon2) -> float:
    """Great-circle distance in metres."""
    import math
    r = 6_371_000.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlam = math.radians(lon2 - lon1)
    a = math.sin(dphi / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dlam / 2) ** 2
    return 2 * r * math.asin(math.sqrt(a))


def _coords(seg) -> Optional[tuple[float, float]]:
    if seg.location_latitude is not None and seg.location_longitude is not None:
        return (seg.location_latitude, seg.location_longitude)
    return None


def _seg_name(seg, name_by_seg: Optional[dict[int, str]]) -> str:
    """Effective display name for a segment — the user's custom label when one
    exists (via name_by_seg), else the segment's geocoded location_name."""
    if name_by_seg is not None and seg.segment_id in name_by_seg:
        return name_by_seg[seg.segment_id] or ""
    return seg.location_name or ""


def _stationary_seconds(group: list) -> int:
    """Total time spent stationary in a group (segments are ~10-min slices, so
    a real stop shows up as large *aggregate* stationary time, not one long seg)."""
    return sum(s.duration for s in group if s.location_stop is True)


def _is_journey(group: list) -> bool:
    """A visit is a journey (transit) when it contains movement and only a brief
    (≤ _WAIT_MAX_S) total stop — a bare move, or a move + platform-wait trip."""
    has_move = any(s.location_stop is False for s in group)
    return has_move and _stationary_seconds(group) <= _WAIT_MAX_S


def _journey_name(group: list, name_by_seg: Optional[dict[int, str]]) -> str:
    """Route label for a transit journey: origin → destination from its move
    ('A → B') labels; falls back to first/last meaningful name."""
    arrows = [n for n in (_seg_name(s, name_by_seg) for s in group) if "→" in n]
    if arrows:
        origin = arrows[0].split("→")[0].strip()
        dest = arrows[-1].split("→")[-1].strip()
        if origin and dest:
            return f"{origin} → {dest}" if origin != dest else origin
    names = [n for n in (_seg_name(s, name_by_seg) for s in group)
             if _norm(n) not in _GENERIC_NAMES]
    return names[0] if names else "In transit"


def _group_anchor(group: list) -> Optional[tuple[float, float]]:
    """Spatial anchor of a visit = the first geolocated segment in it."""
    for s in group:
        c = _coords(s)
        if c:
            return c
    return None


def _representative_name(group: list, name_by_seg: Optional[dict[int, str]]) -> str:
    """
    Pick one name for a visit spanning several POIs: the most common meaningful
    name among its stationary segments (ignoring generic placeholders and
    'A → B' move labels). Falls back to any non-generic name in the group.
    """
    from collections import Counter
    def _clean(names):
        return [
            n for n in names
            if _norm(n) not in _GENERIC_NAMES and "→" not in n
        ]
    stop_names = _clean(
        _seg_name(s, name_by_seg) for s in group if s.location_stop is True
    )
    if stop_names:
        return Counter(stop_names).most_common(1)[0][0]
    any_names = _clean(_seg_name(s, name_by_seg) for s in group)
    if any_names:
        return any_names[0]
    # Transit-only visit: keep its "A → B" move label as the last resort.
    raw = [n for n in (_seg_name(s, name_by_seg) for s in group) if n]
    return raw[0] if raw else ""


def _fetch_segment_modes(session: Session, device: str, date: str) -> dict[int, str]:
    """Dominant transport mode per segment (from ImageGPS.mode)."""
    from collections import Counter
    rows = session.execute(
        select(Image.segment_id, ImageGPS.mode)
        .join(ImageGPS, ImageGPS.image_id == Image.id)
        .where(
            Image.device == device,
            Image.date == date,
            Image.deleted == False,
            Image.segment_id.isnot(None),
            ImageGPS.mode.isnot(None),
        )
    ).all()
    by_seg: dict[int, list[str]] = {}
    for sid, mode in rows:
        by_seg.setdefault(sid, []).append(mode)
    return {sid: Counter(ms).most_common(1)[0][0] for sid, ms in by_seg.items()}


def _group_segments(
    segments: list,
    name_by_seg: Optional[dict[int, str]] = None,
    mode_by_seg: Optional[dict[int, str]] = None,
) -> list[list]:
    """
    Group consecutive segments into visits, distinguishing stops from transit:

      - Stop visits merge consecutive stationary segments by same (labeled) name
        or by centroid within ``_MERGE_RADIUS_M`` of the visit anchor — collapsing
        one venue that resolves to several nearby POI names.
      - A short move (``stop=False``, ≤ ``_MOVE_ABSORB_MAX_S``) whose centroid is
        within radius of the current stop is an in-venue walk and is absorbed into
        that stop.
      - Otherwise consecutive moving segments merge into a single transit visit
        (e.g. bus → tram → walk home becomes one "travelled home"), breaking only
        on the recording-gap window.
      - Tiny unnamed/un-geolocated slivers cling to the current visit.
    """
    def _is_noise_sliver(s) -> bool:
        return (
            _coords(s) is None
            and _norm(_seg_name(s, name_by_seg)) in _GENERIC_NAMES
            and s.duration <= 60
        )

    def _group_is_stop(group: list) -> bool:
        return any(s.location_stop is True for s in group)

    def _near_anchor(group: list, s) -> bool:
        anchor = _group_anchor(group)
        c = _coords(s)
        return bool(anchor and c and _haversine_m(anchor[0], anchor[1], c[0], c[1]) <= _MERGE_RADIUS_M)

    if not segments:
        return []
    ordered = sorted(segments, key=lambda s: s.start_time)
    groups: list[list] = [[ordered[0]]]
    for seg in ordered[1:]:
        group = groups[-1]
        prev = group[-1]
        gap = seg.start_time - prev.end_time
        within_gap = gap <= _VISIT_GAP

        # Noise slivers cling to the current visit.
        if _is_noise_sliver(seg):
            group.append(seg)
            continue

        is_move = seg.location_stop is False
        group_is_stop = _group_is_stop(group)

        if is_move:
            short = seg.duration <= _MOVE_ABSORB_MAX_S
            # In-venue walk: a short move staying within the current stop's radius.
            if group_is_stop and within_gap and short and _near_anchor(group, seg):
                group.append(seg)
            # Otherwise fold into an ongoing transit visit, or start a new one.
            elif (not group_is_stop) and within_gap:
                group.append(seg)
            else:
                groups.append([seg])
            continue

        # Stationary segment: extend a stop visit by same name or proximity.
        if group_is_stop and within_gap:
            same_name = _norm(_seg_name(seg, name_by_seg)) == _norm(
                _representative_name(group, name_by_seg)
            )
            if same_name or _near_anchor(group, seg):
                group.append(seg)
                continue
        groups.append([seg])

    return _merge_transit_waypoints(groups, mode_by_seg)


def _group_mode(group: list, mode_by_seg: dict[int, str]) -> Optional[str]:
    """Dominant transport mode of a group's move segments (None for a stop-only
    group or when no mode is recorded)."""
    from collections import Counter
    if not any(s.location_stop is False for s in group):
        return None
    modes = [mode_by_seg.get(s.segment_id) for s in group if s.segment_id is not None]
    modes = [m for m in modes if m]
    return Counter(modes).most_common(1)[0][0] if modes else None


def _split_core_by_mode(core: list[list], mode_by_seg: Optional[dict[int, str]]) -> list[list]:
    """Split a transit-bounded core (list of groups) into one flattened leg per
    contiguous transport mode, so "walk → bus → walk" becomes three legs. A
    waypoint stop right before a mode change attaches to the upcoming leg (you
    wait, then board). Returns a list of segment-lists."""
    flat_all = [s for g in core for s in g]
    if not mode_by_seg:
        return [flat_all]
    chunks: list[list] = []
    cur: list = []
    cur_mode: Optional[str] = None
    for k, g in enumerate(core):
        m = _group_mode(g, mode_by_seg)
        if m is None and cur and cur_mode is not None:
            nxt = next((mm for mm in (_group_mode(x, mode_by_seg) for x in core[k + 1:]) if mm), None)
            if nxt and nxt != cur_mode:
                chunks.append(cur)
                cur, cur_mode = [], None
        elif m is not None and cur_mode is not None and m != cur_mode and cur:
            chunks.append(cur)
            cur = []
        cur.extend(g)
        if m is not None:
            cur_mode = m
    if cur:
        chunks.append(cur)
    return chunks or [flat_all]


def _merge_transit_waypoints(groups: list[list], mode_by_seg: Optional[dict[int, str]] = None) -> list[list]:
    """
    Fold short waiting-stops (a tram platform, a bus stop) that sit between
    moving segments into a single transit journey. A maximal run of consecutive
    transit groups and short (≤ ``_WAIT_MAX_S``) stop groups that contains at
    least one moving group is merged — so "walk → wait → tram → walk" reads as
    one trip, then split into one leg per contiguous transport mode. Long stops
    (real destinations) and lone short stops with no transit neighbour are left
    untouched.
    """
    def _kind(g: list) -> str:
        # A substantial total stay is a real destination, even if it also
        # contains a few absorbed in-venue-walk move segments.
        if _stationary_seconds(g) > _WAIT_MAX_S:
            return "real_stop"
        if any(s.location_stop is False for s in g):
            return "transit"
        return "short_stop"

    merged: list[list] = []
    i, n = 0, len(groups)
    while i < n:
        if _kind(groups[i]) == "real_stop":
            merged.append(groups[i])
            i += 1
            continue
        # Gather a run of transit / short_stop groups within the gap window.
        run = [groups[i]]
        j = i + 1
        while (
            j < n
            and _kind(groups[j]) in ("transit", "short_stop")
            and (groups[j][0].start_time - groups[j - 1][-1].end_time) <= _VISIT_GAP
        ):
            run.append(groups[j])
            j += 1
        transit_idx = [k for k, g in enumerate(run) if _kind(g) == "transit"]
        if transit_idx:
            first, last = transit_idx[0], transit_idx[-1]
            # Short stops before the first / after the last move are real (brief)
            # stops, not waypoints — keep them separate. Only the transit-bounded
            # core (moves + interior platform waits) merges, then splits by mode.
            for g in run[:first]:
                merged.append(g)
            for leg in _split_core_by_mode(run[first:last + 1], mode_by_seg):
                merged.append(leg)
            for g in run[last + 1:]:
                merged.append(g)
        else:
            merged.append(groups[i])  # only short stops, no transit — keep as-is
        i = j if transit_idx else i + 1
    return merged


def _owner_username(device: str) -> Optional[str]:
    """Resolve the owning user's username for a device (background context —
    no request user available). Returns None if not found."""
    try:
        from auth.types import User
        user = User.find_one({"devices": {"$elemMatch": {"device_id": device, "access_level": "owner"}}})
        if user:
            return user.username
        # Fallback: any user that has the device at all.
        user = User.find_one({"devices": {"$elemMatch": {"device_id": device}}})
        return user.username if user else None
    except Exception as e:
        logger.debug("owner username lookup failed for %s: %s", device, e)
        return None


def _labeled_location_names(session: Session, device: str, date: str) -> set[str]:
    """Normalized names of locations the user has personally labelled (Home/Work/…)."""
    rows = session.execute(
        select(LocationLabel.label)
        .join(Image, Image.location_id == LocationLabel.location_id)
        .where(Image.device == device, Image.date == date)
        .distinct()
    ).scalars().all()
    return {_norm(r) for r in rows if r}


def _is_notable_venue(name: Optional[str], stop: Optional[bool], labeled: set[str]) -> bool:
    """A stop with a real, non-personal POI name is worth an events lookup."""
    n = _norm(name)
    if stop is not True:
        return False
    if n in _GENERIC_NAMES or n in _PERSONAL_NAMES or n in labeled:
        return False
    return True


def _segment_descriptions(session: Session, device: str, date: str, segment_ids: list[int]) -> list[str]:
    """Distinct per-segment activity descriptions for a visit, in time order."""
    rows = session.execute(
        select(Image.segment_id, Image.activity, Image.activity_description)
        .where(
            Image.device == device,
            Image.date == date,
            Image.deleted == False,
            Image.segment_id.in_(segment_ids),
        )
        .order_by(Image.timestamp.asc())
    ).all()
    seen: dict[int, str] = {}
    for sid, activity, desc in rows:
        if sid in seen:
            continue
        if (activity or "").strip().lower() in _SKIP_ACTIVITIES:
            continue
        text = (desc or "").strip() or (activity or "").strip()
        if text:
            seen[sid] = text
    return list(seen.values())


def _visit_people(session: Session, device: str, date: str, segment_ids: list[int]) -> list[str]:
    from tasks import _ANONYMOUS_FACE_LABELS  # reuse the ingest anonymous set
    labels = session.execute(
        select(ImagePerson.label)
        .join(Image, Image.id == ImagePerson.image_id)
        .where(
            Image.device == device,
            Image.date == date,
            Image.deleted == False,
            Image.segment_id.in_(segment_ids),
            ImagePerson.label.isnot(None),
            ImagePerson.label != "",
            ImagePerson.label.notin_(list(_ANONYMOUS_FACE_LABELS - {None, ""})),
        )
    ).scalars().all()
    return sorted({l for l in labels if l})


def _events_prompt(
    location_name: str,
    date_human: str,
    lat: Optional[float],
    lon: Optional[float],
    scene_hint: str,
) -> str:
    loc_parts = []
    if lat is not None and lon is not None:
        loc_parts.append(f"coordinates {lat:.5f}, {lon:.5f}")
    if location_name:
        loc_parts.append(f'nearby place name "{location_name}"')
    where = " (".join(loc_parts) + (")" if len(loc_parts) > 1 else "")

    scene = (
        f" The photos taken there show: {scene_hint}."
        if scene_hint else ""
    )
    return (
        f"On {date_human}, at {where}.{scene}\n"
        "Identify the specific named public event (concert, match, festival, "
        "tattoo, parade, exhibition, market) happening at this exact location "
        "and date. Use the coordinates as the primary anchor; the place name may "
        "be a generic or adjacent label.\n"
        "CRITICAL — report an event ONLY if the photos are consistent with the "
        "person actually ATTENDING it: a crowd, a stage or performance, a sports "
        "field/arena bowl, exhibits, festival stalls, tickets/programmes. If the "
        "photos instead show unrelated activity — working at a laptop, a meeting, "
        "eating at a cafe or restaurant, an office/lobby/corridor/desk, or just "
        "passing by outside — reply NONE even when an event is on at or near this "
        "venue. Being at the location is not the same as attending.\n"
        "Reply with ONE short factual line naming the event, or exactly NONE if "
        "nothing clearly matches or attendance is not evident."
    )


_EVENT_HEDGE_PREFIXES = (
    "which", "please", "could you", "can you", "i'm not sure", "im not sure",
    "i am not sure", "it's unclear", "its unclear", "there are multiple",
    "i don't", "i do not", "sorry",
)


def _clean_event_text(resp) -> Optional[str]:
    import re
    text = (str(resp) if resp else "").strip()
    # Strip markdown citation tails like " ([site.com](https://…))" that
    # OpenAI web_search appends.
    text = re.sub(r"\s*\(\[[^\]]*\]\([^)]*\)\)", "", text).strip()
    if not text or "none" in text.lower()[:12] or len(text) > 300:
        return None
    low = text.lower()
    # Reject clarifying questions / hedges — the model is unsure, not reporting
    # a real event (e.g. "Which Kasernenhof do you mean?").
    if "?" in text or low.startswith(_EVENT_HEDGE_PREFIXES):
        return None
    return text


def _lookup_events(
    location_name: str,
    date_human: str,
    lat: Optional[float] = None,
    lon: Optional[float] = None,
    scene_hint: str = "",
) -> Optional[str]:
    """
    Web-search-grounded lookup of the event at a venue on a date.

    Grounds on coordinates (primary anchor) + a short hint of what the photos
    show, so a generic/adjacent POI name ("Kasernenhof") doesn't pull an
    unrelated nearby event. Tries the active provider's grounded search first
    (OpenAI web_search / Gemini google_search), then Gemini directly. Returns a
    short factual note, or None when nothing matches / on error.
    """
    prompt = _events_prompt(location_name, date_human, lat, lon, scene_hint)

    # 1. Active provider (OpenAI web_search when mode=openai; Gemini otherwise).
    try:
        resp = llm.generate_from_text(prompt, use_search=True)  # type: ignore[call-arg]
        cleaned = _clean_event_text(resp)
        if cleaned:
            return cleaned
    except Exception as e:
        logger.debug("active-provider events lookup failed for %s: %s", location_name, e)

    # 2. Fallback: Gemini google_search grounding directly.
    try:
        from integrations.llm.gemini import llm as gemini_llm
        if gemini_llm is not llm:
            resp = gemini_llm.generate_from_text(prompt, use_search=True)
            return _clean_event_text(resp)
    except Exception as e:
        logger.warning("gemini events fallback failed for %s: %s", location_name, e)
    return None


_MAX_NOTES_PER_VISIT = 6


def _parse_visit_json(resp) -> dict[int, str]:
    """Extract {index: sentence} from an LLM response (tolerant of fences/partial)."""
    text = (str(resp) if resp else "").strip()
    if "```" in text:
        # keep the largest fenced block
        parts = [p for p in text.split("```") if "{" in p]
        if parts:
            text = max(parts, key=len).replace("json", "", 1)
    for loader in (json.loads, _json_parser.parse):
        try:
            obj = loader(text)
            if isinstance(obj, dict):
                return {int(k): str(v).strip() for k, v in obj.items() if str(v).strip()}
        except Exception:
            continue
    return {}


def _describe_visits_global(outline: list[dict]) -> dict[int, str]:
    """
    ONE LLM call describing every visit with the whole day in view, so
    descriptions connect and don't repeat. `outline` is one dict per visit:
    {index, place, kind ('stop'|'transit'), time_range, people, event, notes}.
    Returns {index: sentence}; missing entries fall back at the call site.
    """
    if not outline:
        return {}

    lines: list[str] = []
    for o in outline:
        head = f"Visit {o['index']} — {o['place']} [{o['kind']}], {o['time_range']}"
        if o.get("people"):
            head += f"; with {', '.join(o['people'])}"
        if o.get("event"):
            head += f"; Event: {o['event']}"
        lines.append(head)
        notes = o.get("notes") or []
        if notes:
            joined = " ".join(f"- {n}" for n in notes[:_MAX_NOTES_PER_VISIT])
            lines.append(f"    notes: {joined}")

    prompt = (
        "Below is one person's whole day from a POV lifelogging camera, as an ordered "
        "list of location visits. Each visit has a place, whether it was a stop or "
        "transit, a time range, and short notes distilled from the photos.\n\n"
        "Using the FULL day for context (so the descriptions connect and do not repeat "
        "each other), write ONE factual sentence per visit. Past tense, third person "
        "'they'. Answer the concrete questions a diary cares about: WHAT they did there "
        "and WHO they were with. State it plainly.\n\n"
        "Write like a log entry, NOT prose. Do NOT be flowery, literary, or atmospheric. "
        "Do NOT set a scene or dwell on incidental visual micro-details (lighting, decor, "
        "what was on a screen, passing objects) — report the actual activity, not what the "
        "camera happened to see. Skip filler adjectives.\n\n"
        "Only mention duration when it is genuinely notable (an unusually long stay, or a "
        "very brief stop); otherwise leave time out — the app already shows it. Keep stop "
        "visits to ~18 words. For a transit visit, state the mode and route in one line "
        "(walk / tram / train / drive), and a wait only if long (give the minutes); up to "
        "~25 words. A visit may list an Event, but name it ONLY when the notes clearly "
        "show the person attending it (crowd, performance, match, exhibits); if the notes "
        "describe unrelated activity (working, a meeting, eating, passing through), IGNORE "
        "the event and describe what they actually did. Do not invent facts beyond the "
        "notes. Do not restate the place name or the clock time.\n\n"
        "Return ONLY a JSON object mapping each visit number (as a string) to its "
        'sentence, e.g. {"0": "...", "1": "..."}.\n\n'
        + "\n".join(lines)
    )

    try:
        resp = llm.generate_from_text(prompt)
        return _parse_visit_json(resp)
    except Exception as e:
        logger.error("global visit description failed: %s", e)
        return {}


def build_location_visits(
    session: Session, device: str, date: str, segments: list
) -> list:
    """
    Group the day's segments into location visits and generate one specific
    description per visit (with optional current-events grounding for notable
    venues). Returns a list of LocationVisit.
    """
    from schemas import LocationVisit  # local import to avoid cycles
    from services.summary import _fetch_segment_locations

    # Resolve the device owner's custom labels (Home/Work/…) so visits are named
    # and grouped the same way MainPage/DayNav shows them — not by raw geocode.
    owner = _owner_username(device)
    seg_loc = _fetch_segment_locations(session, device, date, username=owner)
    name_by_seg = {sid: v[0] for sid, v in seg_loc.items()}
    mode_by_seg = _fetch_segment_modes(session, device, date)

    groups = _group_segments(segments, name_by_seg, mode_by_seg)
    if not groups:
        return []

    labeled = _labeled_location_names(session, device, date)

    visits: list = []
    outline: list[dict] = []
    for idx, group in enumerate(groups):
        seg_ids = [s.segment_id for s in group if s.segment_id is not None]
        start_time = group[0].start_time
        end_time = group[-1].end_time
        duration = max(int((end_time - start_time).total_seconds()), 10)
        duration_min = max(1, duration // 60)
        # Journeys (bare moves, or move + platform-wait trips) are named by route
        # and marked as transit; real stops are named by their venue and marked
        # as a stop (in-venue walks don't demote a stop to transit).
        journey = _is_journey(group)
        name = _journey_name(group, name_by_seg) if journey else _representative_name(group, name_by_seg)
        stop = not journey
        lat = next((s.location_latitude for s in group if s.location_latitude is not None), None)
        lon = next((s.location_longitude for s in group if s.location_longitude is not None), None)
        activity_groups = list(dict.fromkeys(s.activity_group for s in group if s.activity_group))

        seg_descs = _segment_descriptions(session, device, date, seg_ids) if seg_ids else []
        people = _visit_people(session, device, date, seg_ids) if seg_ids else []

        event_context: Optional[str] = None
        if (
            duration >= _EVENT_MIN_STOP_S
            and _is_notable_venue(name, stop, labeled)
            and _attendance_plausible(activity_groups)
        ):
            date_human = start_time.strftime("%A, %-d %B %Y")
            scene_hint = " ".join(seg_descs[:3])[:300]
            event_context = _lookup_events(name, date_human, lat=lat, lon=lon, scene_hint=scene_hint)

        time_range = f"{start_time.strftime('%H:%M')}–{end_time.strftime('%H:%M')}"
        outline.append({
            "index": idx,
            "place": name or "an unnamed place",
            "kind": "stop" if stop else "transit",
            "time_range": f"{time_range} ({duration_min} min)",
            "people": people,
            "event": event_context,
            "notes": seg_descs,
        })

        visits.append(
            LocationVisit(
                visit_index=idx,
                location_name=name or None,
                location_stop=stop,
                location_latitude=lat,
                location_longitude=lon,
                start_time=start_time,
                end_time=end_time,
                duration=duration,
                timezone=next((s.timezone for s in group if getattr(s, "timezone", None)), None),
                segment_ids=seg_ids,
                segment_indices=[s.segment_index for s in group if s.segment_index is not None],
                activity_groups=activity_groups,
                description="",  # filled by the single whole-day description call below
                event_context=event_context,
            )
        )

    # One LLM call describes every visit with the full day in view.
    descriptions = _describe_visits_global(outline)
    for v, o in zip(visits, outline):
        v.description = descriptions.get(v.visit_index) or (o["notes"][0] if o["notes"] else "")

    return visits

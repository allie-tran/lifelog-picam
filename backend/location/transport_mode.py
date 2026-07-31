"""
transport_mode.py
-----------------
Per-segment transport-mode classification + flight-aware GPS interpolation.

GPS kinematics are the sole signal: segment speed (robust p85) + the *main
trajectory* (net displacement + path straightness) + whether the endpoints sit
inside airport footprints decide the mode (stationary/walk/cycle/vehicle/flight).
A fast p85 alone is spike-prone, so the trajectory shape vetoes "vehicle" calls
that don't actually cover ground.

Public API:
    classify_segment_gps(speed_p85, dist_m, is_flight, straightness, n_points) -> str
    is_flight_pair(lat1, lon1, lat2, lon2, dt_s)            -> bool
    great_circle_point(lat1, lon1, lat2, lon2, frac)        -> (lat, lon)
"""

from __future__ import annotations

import logging
import math
import re

from location.airports import nearest_airport

logger = logging.getLogger(__name__)

# ─── Mode vocabulary ──────────────────────────────────────────────────────────
# Stored verbatim in ImageGPS.mode.
STATIONARY = "stationary"
WALK = "walk"
CYCLE = "cycle"
VEHICLE = "vehicle"           # GPS-only motor vehicle, before sub-type disambiguation
FLIGHT = "flight"

# Specific ground-vehicle sub-modes. GPS kinematics can't tell these apart (they
# share the vehicle speed band), so they're resolved from the segment's photos —
# the annotation LLM already sees a tram/train/ferry interior. Following the POI
# disambiguation pattern: GPS gives the coarse class, the photos pick the sub-type.
CAR = "car"
BUS = "bus"
TRAM = "tram"
TRAIN = "train"
SUBWAY = "subway"
FERRY = "ferry"
CABLE_CAR = "cable_car"

# Sub-modes the disambiguator may return; anything else falls back to VEHICLE.
VEHICLE_SUBMODES = {CAR, BUS, TRAM, TRAIN, SUBWAY, FERRY, CABLE_CAR}

# Every "moving" mode. An explicit photo-named mode may override any of these (a
# slow ferry/tram lands in the walk/cycle speed band and would otherwise stick),
# but never STATIONARY or FLIGHT.
MOVE_MODES = {WALK, CYCLE, VEHICLE} | VEHICLE_SUBMODES

# Below this the photo evidence is too weak to override the generic "vehicle".
MODE_LLM_CONF_THRESHOLD = 0.6

# Activity labels carrying no transport signal — dropped so "no activity"/idle
# frames don't dilute the cues handed to the sub-mode disambiguator.
_SKIP_MODE_ACTIVITIES = {"no activity", "unclear", "unclear activity", ""}

# ─── GPS speed bins (m/s, on the robust p85 of intra-segment speeds) ───────────
WALK_MAX = 2.0               # ≈7.2 km/h
CYCLE_MAX = 6.0              # ≈25 km/h
# above CYCLE_MAX → VEHICLE, unless flight conditions hold

# Flight fallback when airport endpoints are missing (e.g. one fix lost):
# sustained > ~430 km/h over a long hop is unambiguously airborne.
FLIGHT_SPEED = 120.0         # m/s ≈ 432 km/h
FLIGHT_MIN_DIST = 50_000.0   # m — guard against a single spurious fast sample

# ─── Main-trajectory guard ────────────────────────────────────────────────────
# A high p85 over a segment that barely advances and wanders is almost always GPS
# spike noise on a stationary/walking stretch, not a vehicle. Real vehicle travel
# covers ground in a fairly direct line. Demote a "vehicle" p85 to walk when the
# segment's net displacement is small AND its path is very winding — but only when
# it holds enough GPS points for the shape to mean anything (with only 2–3 fixes
# "straightness" is random, so the veto would wrongly demote real vehicles).
VEHICLE_MIN_SPAN = 300.0       # m — net displacement a real vehicle clears
STRAIGHTNESS_MIN = 0.5         # span / path-length below this = very winding (local wander)
VEHICLE_VETO_MIN_POINTS = 4    # need ≥4 fixes (≥3 hops) before trusting the shape veto


# ─── Geometry ─────────────────────────────────────────────────────────────────

def _haversine_m(lat1, lon1, lat2, lon2) -> float:
    R = 6_371_000.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp = math.radians(lat2 - lat1)
    dl = math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * R * math.asin(math.sqrt(a))


def great_circle_point(lat1, lon1, lat2, lon2, frac: float) -> tuple[float, float]:
    """
    Point at fraction ``frac`` (0..1) along the great-circle arc from
    (lat1,lon1) to (lat2,lon2).  Slerp on the unit sphere — gives the curved
    flight path instead of a straight lat/lon blend, which matters over the
    long hops where the two differ by hundreds of km.
    """
    p1, l1 = math.radians(lat1), math.radians(lon1)
    p2, l2 = math.radians(lat2), math.radians(lon2)
    # angular distance between the two points
    d = 2 * math.asin(math.sqrt(
        math.sin((p2 - p1) / 2) ** 2
        + math.cos(p1) * math.cos(p2) * math.sin((l2 - l1) / 2) ** 2
    ))
    sin_d = math.sin(d)
    # d == 0 (coincident) or d == π (antipodal) → sin(d) == 0, slerp undefined.
    # No real flight pair is antipodal; fall back to the linear blend.
    if abs(sin_d) < 1e-12:
        return (
            lat1 + frac * (lat2 - lat1),
            lon1 + frac * (lon2 - lon1),
        )
    a = math.sin((1 - frac) * d) / sin_d
    b = math.sin(frac * d) / sin_d
    x = a * math.cos(p1) * math.cos(l1) + b * math.cos(p2) * math.cos(l2)
    y = a * math.cos(p1) * math.sin(l1) + b * math.cos(p2) * math.sin(l2)
    z = a * math.sin(p1) + b * math.sin(p2)
    lat = math.atan2(z, math.hypot(x, y))
    lon = math.atan2(y, x)
    return math.degrees(lat), math.degrees(lon)


# ─── Flight detection ─────────────────────────────────────────────────────────

def is_flight_pair(lat1, lon1, lat2, lon2, dt_s: float) -> bool:
    """
    True when the hop from point 1 to point 2 is a flight.

    Primary signal: both endpoints fall inside an airport footprint
    (``nearest_airport`` only matches when geometrically inside).  Fallback:
    sustained airborne speed over a long-enough hop, for when one airport fix
    was lost.
    """
    airport1 = nearest_airport(lat1, lon1)
    airport2 = nearest_airport(lat2, lon2)
    if airport1 and airport2:
        return airport1["name"] != airport2["name"]
    dist = _haversine_m(lat1, lon1, lat2, lon2)
    if dt_s > 0 and dist >= FLIGHT_MIN_DIST and (dist / dt_s) >= FLIGHT_SPEED:
        return True
    return False


# ─── GPS-only mode ────────────────────────────────────────────────────────────

def classify_segment_gps(
    speed_p85: float,
    dist_m: float,
    is_flight: bool,
    straightness: float,
    n_points: int,
) -> str:
    """Coarse mode from kinematics + main-trajectory shape.

    ``dist_m`` is the window's net start→end displacement; ``straightness`` is
    that displacement divided by the cumulative path length (1.0 = dead straight,
    →0 = wanders in place); ``n_points`` is how many GPS fixes the window holds.
    Span and straightness describe the main trajectory and veto a "vehicle" speed
    that the trajectory doesn't support (GPS spikes over a near-stationary or
    winding walk) — but only once ``n_points`` is large enough for the shape to be
    real (a sparse window can't tell straight from winding, so the veto is skipped).
    All args are required: trajectory metrics are always available at the call site,
    and an optional metric that silently no-ops the veto is a call-site trap.
    """
    if is_flight:
        return FLIGHT
    if speed_p85 >= FLIGHT_SPEED and dist_m >= FLIGHT_MIN_DIST:
        return FLIGHT
    if speed_p85 < WALK_MAX:
        return WALK
    if speed_p85 < CYCLE_MAX:
        return CYCLE
    # Vehicle band by speed — confirm against the main trajectory. A fast p85 over
    # a move that neither advances far nor travels in a line is spike noise, not a
    # vehicle: demote to walk. Skip the veto when the window is too sparse to trust
    # its shape (else a 2–3 fix slice of a real vehicle move gets demoted).
    if (
        n_points >= VEHICLE_VETO_MIN_POINTS
        and dist_m < VEHICLE_MIN_SPAN
        and straightness < STRAIGHTNESS_MIN
    ):
        return WALK
    return VEHICLE


# ─── Vehicle sub-mode disambiguation (photos + kinematics) ────────────────────

# Keyword → sub-mode. The describe LLM already names the mode in the activity label
# ("Travelling (Tram)", "riding a ferry"), so most trips resolve by a free substring
# match — no extra LLM call. Order matters: check "cable car" before "car", "subway"
# before generic rail words. Checked against the lowercased activity string.
_MODE_KEYWORDS: list[tuple[tuple[str, ...], str]] = [
    (("cable car", "cablecar", "gondola", "funicular", "aerial tram", "ropeway"), CABLE_CAR),
    (("subway", "metro", "underground", "u-bahn"), SUBWAY),
    (("tram", "streetcar", "light rail", "s-bahn"), TRAM),
    (("train", "rail", "railway"), TRAIN),
    (("ferry", "boat", "ship"), FERRY),
    (("bus", "coach", "shuttle"), BUS),
    (("car", "taxi", "driving", "cab", "uber"), CAR),
]


# Whole-word keyword matchers. A bare substring match is wrong here: "rail"
# lives inside "trail", so "Hiking on a trail" would map to TRAIN. Match on word
# boundaries so only the standalone word counts (hyphens like "u-bahn" are inner
# boundaries, so \b still brackets the whole token).
_MODE_MATCHERS: list[tuple[re.Pattern, str]] = [
    (re.compile(r"\b(?:%s)\b" % "|".join(re.escape(k) for k in keys)), mode)
    for keys, mode in _MODE_KEYWORDS
]


def mode_from_activity(activity: str) -> str | None:
    """Map a describe activity label to a sub-mode by keyword, or None. Free — no
    LLM. E.g. 'Travelling (Tram)' → tram, 'riding the ferry' → ferry."""
    low = (activity or "").lower()
    for pat, mode in _MODE_MATCHERS:
        if pat.search(low):
            return mode
    return None


# ─── Pedestrian (walk / cycle) detection from photos ──────────────────────────
# The GPS cycle band (WALK_MAX..CYCLE_MAX) is narrow and easily faked by walk-pace
# GPS jitter, so a real walk often lands on "cycle". The photos tell the two apart
# (a bike/handlebars vs. just walking). Only used to correct *within* the walk↔cycle
# band — never to demote a vehicle, so an incidental "walking" frame on a bus trip
# can't turn the ride into a walk. Cycle checked first: a bike photo is decisive.
_PEDESTRIAN_KEYWORDS: list[tuple[tuple[str, ...], str]] = [
    (("cycling", "biking", "bicycle", "bike", "cycle"), CYCLE),
    (("walking", "walk", "hiking", "hike", "strolling", "stroll",
      "on foot", "trekking", "wandering"), WALK),
]

_PEDESTRIAN_MATCHERS: list[tuple[re.Pattern, str]] = [
    (re.compile(r"\b(?:%s)\b" % "|".join(re.escape(k) for k in keys)), mode)
    for keys, mode in _PEDESTRIAN_KEYWORDS
]


def pedestrian_mode_from_activity(activity: str) -> str | None:
    """Map an activity label to WALK or CYCLE by keyword, or None. Free — no LLM.
    E.g. 'Walking With Others' → walk, 'Cycling Along River' → cycle."""
    low = (activity or "").lower()
    for pat, mode in _PEDESTRIAN_MATCHERS:
        if pat.search(low):
            return mode
    return None


def disambiguate_vehicle_mode(
    activity_labels: list[tuple[str, int]],
    speed_kmh: float,
    ascent_m: float,
    straightness: float,
) -> str | None:
    """
    Refine a GPS "vehicle" move into a specific mode (car/bus/tram/train/subway/
    ferry/cable_car) using the segment's photo activities plus a few kinematic
    hints, via the annotation LLM.

    GPS speed alone can't separate these — a tram, bus and car all sit in the same
    band — but the photos usually can (rails and overhead wires, a ferry deck and
    water, a cable-car cabin, a train carriage). This mirrors the stop-POI
    disambiguator: kinematics give the coarse class, the photos pick the sub-type.
    ``ascent_m`` (total climb over the move) is the tell for a cable car; a low,
    winding, slow-ish track over water hints ferry. Returns the chosen mode string,
    or None to keep the generic ``VEHICLE`` when the evidence is weak/ambiguous.
    """
    from integrations.llm import llm  # local import — avoids a module import cycle

    labels = [
        (str(a).strip(), int(n)) for a, n in (activity_labels or [])
        if a and str(a).strip().lower() not in _SKIP_MODE_ACTIVITIES
    ]
    if not labels:
        return None

    # Fast path — the describe annotation usually names the mode already. Take the
    # keyword-mapped mode of the most-seen label that maps to one; no LLM call.
    for label, _n in labels:
        mapped = mode_from_activity(label)
        if mapped:
            logger.info("Vehicle sub-mode from activity %r → %s", label, mapped)
            return mapped

    act_lines = "\n".join(f"- {label} (seen in {n} photos)" for label, n in labels)
    prompt = (
        "A lifelogger was moving at vehicle speed (GPS says a motorised trip, not "
        "walking or cycling). Decide the SPECIFIC mode of transport from what their "
        "photos show, backed by the motion.\n\n"
        f"Activities observed during the trip (from their photos):\n{act_lines}\n\n"
        "Motion over the trip:\n"
        f"- typical speed ~{speed_kmh:.0f} km/h\n"
        f"- total climb ~{ascent_m:.0f} m (a large climb over a short trip suggests a "
        "cable car / funicular / gondola)\n"
        f"- path straightness {straightness:.2f} (1.0 = dead straight rails/road, lower = winding)\n\n"
        "Choose ONE of: car, bus, tram, train, subway, ferry, cable_car. Weigh the "
        "photos most: rails/overhead wires and a street => tram; a train carriage / "
        "platform => train; underground / metro => subway; a bus interior => bus; open "
        "water / a deck => ferry; a hanging cabin with a big climb => cable_car; "
        "otherwise a private car. If the photos don't clearly indicate any of these, "
        "return null (keep it generic).\n\n"
        'Respond with ONLY JSON: {"mode": "<one of the list, or null>", '
        '"confidence": <0.0-1.0>, "reason": "<short>"}'
    )

    try:
        result = llm.generate_from_text(prompt, parse_json=True)
    except Exception as exc:
        logger.warning("LLM vehicle-mode disambiguation failed: %s", exc)
        return None
    if not isinstance(result, dict):
        return None

    mode = str(result.get("mode") or "").strip().lower()
    try:
        conf = float(result.get("confidence", 0.0))
    except (TypeError, ValueError):
        conf = 0.0
    if mode not in VEHICLE_SUBMODES or conf < MODE_LLM_CONF_THRESHOLD:
        return None
    logger.info(
        "LLM vehicle sub-mode: %s (conf=%.2f, ~%.0f km/h, ascent %.0f m) — %s",
        mode, conf, speed_kmh, ascent_m, result.get("reason", ""),
    )
    return mode

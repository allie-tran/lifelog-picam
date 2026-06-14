"""
transport_mode.py
-----------------
Per-segment transport-mode classification + flight-aware GPS interpolation.

GPS is the primary signal; visual only confirms it:

  1. GPS kinematics — segment speed (robust p85) + the *main trajectory*
     (net displacement + path straightness) + whether the endpoints sit inside
     airport footprints.  Cheap, always available, and the authority for the
     mode itself (stationary/walk/cycle/vehicle/flight).  A fast p85 alone is
     spike-prone, so the trajectory shape vetoes "vehicle" calls that don't
     actually cover ground, and a post-pass smooths short single-segment blips
     out of the mode timeline.
  2. CLIP visual — zero-shot first-person classification over the segment's
     images, using the prompts/labels and θ=0.75 confidence gate from VAISL
     (Tran et al., "Visual-Aware Identification of Semantic Locations in
     Lifelog", MMM 2023).  Confirm-only: its sole job is to split the GPS
     "vehicle" bucket into car vs public_transport, which GPS speed cannot
     resolve.  A sub-θ or disagreeing label is ignored; CLIP never overrides
     the GPS mode.  Skipped gracefully when no embeddings are present.

Public API:
    classify_segment_gps(speed_p85, dist_m, is_flight, straightness, n_points) -> str
    is_flight_pair(lat1, lon1, lat2, lon2, dt_s)            -> bool
    great_circle_point(lat1, lon1, lat2, lon2, frac)        -> (lat, lon)
    fuse_mode(gps_mode, clip_mode)                          -> str
    clip_mode_for_features(features)                         -> str | None
"""

from __future__ import annotations

import logging
import math

import numpy as np

from location.airports import nearest_airport

logger = logging.getLogger(__name__)

# ─── Mode vocabulary ──────────────────────────────────────────────────────────
# Stored verbatim in ImageGPS.mode.
STATIONARY = "stationary"
WALK = "walk"
CYCLE = "cycle"
VEHICLE = "vehicle"           # GPS-only car/bus/train (CLIP may refine)
CAR = "car"
PUBLIC_TRANSPORT = "public_transport"
FLIGHT = "flight"
UNKNOWN = "unknown"

# ─── GPS speed bins (m/s, on the robust p85 of intra-segment speeds) ───────────
WALK_MAX = 2.0               # ≈7.2 km/h
CYCLE_MAX = 7.0              # ≈25 km/h
# above CYCLE_MAX → VEHICLE, unless flight conditions hold

# Flight fallback when airport endpoints are missing (e.g. one fix lost):
# sustained > ~430 km/h over a long hop is unambiguously airborne.
FLIGHT_SPEED = 120.0         # m/s ≈ 432 km/h
FLIGHT_MIN_DIST = 50_000.0   # m — guard against a single spurious fast sample

# ─── Main-trajectory guard ────────────────────────────────────────────────────
# A high p85 over a window that barely advances and wanders is almost always GPS
# spike noise on a stationary/walking stretch, not a vehicle. Real vehicle travel
# covers ground in a fairly direct line. Demote a "vehicle" p85 to walk when the
# window's net displacement is small AND its path is very winding — but only when
# the window holds enough GPS points for the shape to mean anything. classify is
# called on short per-image windows (±LOCAL_MODE_HALF_WINDOW_S); with only 2–3
# fixes "straightness" is random, so the veto would wrongly demote real vehicles.
VEHICLE_MIN_SPAN = 300.0       # m — net displacement a real vehicle clears in the window
STRAIGHTNESS_MIN = 0.5         # span / path-length below this = very winding (local wander)
VEHICLE_VETO_MIN_POINTS = 4    # need ≥4 fixes (≥3 hops) before trusting the shape veto

# A run of consecutive same-mode images shorter than this is too brief to trust
# on its own. If the runs on both sides share one mode, the blip is absorbed into
# them — kills window-scale flicker from p85 jitter within a move.
MIN_MODE_DURATION_S = 60.0


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
    if nearest_airport(lat1, lon1) and nearest_airport(lat2, lon2):
        return True
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


# ─── CLIP visual refinement ───────────────────────────────────────────────────

# class name → stored mode.
# Prompts and label set follow VAISL (Tran et al., MMM 2023, Table 1): simple
# first-person statements classify far more reliably than scene descriptions,
# and "airport"/"building" both fold into the indoor→stationary bucket.
_CLIP_CLASSES: dict[str, str] = {
    "sitting on an airplane": FLIGHT,
    "in a car": CAR,
    "in a public transport": PUBLIC_TRANSPORT,
    "walking outside": WALK,
    "in an airport": STATIONARY,
    "inside a building or a house": STATIONARY,
}
_CLIP_PROMPTS = [
    "I am {}",
]

# VAISL θ: a CLIP label is only trusted to confirm the GPS mode when its modal
# probability clears this. Below it the scene is too ambiguous to override the
# generic GPS "vehicle" bucket, so the segment stays VEHICLE.
CLIP_CONF_THRESHOLD = 0.75

_classifier = None
_class_modes: list[str] = []


def _get_classifier():
    """Lazily build the CLIP zero-shot classifier (loads the shared model)."""
    global _classifier, _class_modes
    if _classifier is None:
        from services.clip_classifier import ClipPromptClassifier
        names = list(_CLIP_CLASSES.keys())
        _class_modes = [_CLIP_CLASSES[n] for n in names]
        _classifier = ClipPromptClassifier(names, prompt_templates=_CLIP_PROMPTS)
    return _classifier


def clip_mode_for_features(features: np.ndarray) -> str | None:
    """
    Modal CLIP scene mode over a segment's image features (N, D), following
    VAISL: average-pool the per-image probabilities into one event vector, take
    the argmax label, and return it only when its probability clears
    ``CLIP_CONF_THRESHOLD`` (θ). Returns None on empty features, an unavailable
    model, or a sub-θ (ambiguous) label.
    """
    if features is None or len(features) == 0:
        return None
    try:
        clf = _get_classifier()
        probs = clf.predict_proba_from_features(np.asarray(features, dtype=np.float32))
        pooled = probs.mean(axis=0)                  # average over images, then pick
        idx = int(pooled.argmax())
        if pooled[idx] < CLIP_CONF_THRESHOLD:
            return None
        return _class_modes[idx]
    except Exception as exc:                          # model missing / dim mismatch
        logger.warning("CLIP mode classification failed: %s", exc)
        return None


# ─── Fusion ───────────────────────────────────────────────────────────────────

def fuse_mode(gps_mode: str, clip_mode: str | None) -> str:
    """
    GPS decides the mode; CLIP only *confirms* it — never overrides.

    GPS kinematics are authoritative for the mode itself (stationary / walk /
    cycle / vehicle / flight). The single thing GPS cannot resolve is the
    vehicle sub-type, so CLIP is allowed one job: confirm whether the GPS
    "vehicle" bucket is a car or public transport. Everywhere else CLIP is
    advisory only — a disagreeing scene label is ignored, and CLIP can never
    promote a non-flight GPS mode to flight (a lost airport fix is handled by
    the GPS airspeed fallback in ``is_flight_pair``, not by the camera).
    """
    if gps_mode == VEHICLE and clip_mode in (CAR, PUBLIC_TRANSPORT):
        return clip_mode
    return gps_mode or UNKNOWN

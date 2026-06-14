"""
transport_mode.py
-----------------
Per-segment transport-mode classification + flight-aware GPS interpolation.

Two signals are fused:

  1. GPS kinematics — segment speed (robust p85) + distance + whether the
     endpoints sit inside airport footprints.  Cheap, always available, and the
     authority for slow modes (walk/cycle) and for flights (airport-to-airport).
  2. CLIP visual — zero-shot first-person scene classification over the
     segment's images (airplane cabin / car / bus-or-train / street / bike /
     indoor).  Splits the GPS "vehicle" bucket into car vs public_transport and
     confirms flights.  Skipped gracefully when no embeddings are present.

Public API:
    classify_segment_gps(speed_p85, dist_m, is_flight)      -> str
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

def classify_segment_gps(speed_p85: float, dist_m: float, is_flight: bool) -> str:
    """Coarse mode from kinematics alone."""
    if is_flight:
        return FLIGHT
    if speed_p85 >= FLIGHT_SPEED and dist_m >= FLIGHT_MIN_DIST:
        return FLIGHT
    if speed_p85 < WALK_MAX:
        return WALK
    if speed_p85 < CYCLE_MAX:
        return CYCLE
    return VEHICLE


# ─── CLIP visual refinement ───────────────────────────────────────────────────

# class name → stored mode
_CLIP_CLASSES: dict[str, str] = {
    "the interior of an airplane cabin": FLIGHT,
    "the interior of a car": CAR,
    "the interior of a bus or train": PUBLIC_TRANSPORT,
    "a city street seen while walking": WALK,
    "riding a bicycle outdoors": CYCLE,
    "an indoor room": STATIONARY,
}
_CLIP_PROMPTS = [
    "a first-person lifelog photo of {}",
    "a photo of {}",
]

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
    Modal CLIP scene mode over a segment's image features (N, D).
    Returns None if features are empty or the model is unavailable.
    """
    if features is None or len(features) == 0:
        return None
    try:
        clf = _get_classifier()
        probs = clf.predict_proba_from_features(np.asarray(features, dtype=np.float32))
        idx = probs.mean(axis=0).argmax()           # average over images, then pick
        return _class_modes[idx]
    except Exception as exc:                          # model missing / dim mismatch
        logger.warning("CLIP mode classification failed: %s", exc)
        return None


# ─── Fusion ───────────────────────────────────────────────────────────────────

def fuse_mode(gps_mode: str, clip_mode: str | None) -> str:
    """
    Combine the GPS prior with the CLIP scene label.

    - Slow GPS modes (walk/cycle) and stationary are speed-reliable → keep GPS.
    - GPS flight wins outright (airport-to-airport is hard evidence); CLIP only
      promotes *to* flight when GPS missed it (e.g. lost airport fix).
    - The ambiguous GPS "vehicle" bucket defers to CLIP to split car vs
      public_transport; if CLIP is silent it stays the generic VEHICLE.
    """
    if gps_mode == FLIGHT:
        return FLIGHT
    if clip_mode == FLIGHT:
        return FLIGHT
    if gps_mode in (STATIONARY, WALK, CYCLE):
        return gps_mode
    if gps_mode == VEHICLE:
        if clip_mode in (CAR, PUBLIC_TRANSPORT):
            return clip_mode
        return VEHICLE
    return gps_mode or UNKNOWN

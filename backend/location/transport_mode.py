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

import math

from location.airports import nearest_airport

# ─── Mode vocabulary ──────────────────────────────────────────────────────────
# Stored verbatim in ImageGPS.mode.
STATIONARY = "stationary"
WALK = "walk"
CYCLE = "cycle"
VEHICLE = "vehicle"           # GPS-only car / bus / train (no sub-type split)
FLIGHT = "flight"

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

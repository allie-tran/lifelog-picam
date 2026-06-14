"""
airports.py
-----------
Offline airport gazetteer lookup.

Nominatim reverse-geocoding never returns the enclosing aerodrome polygon (it
returns an unnamed aeroway node, a taxiway, or an admin boundary), and Overpass
`is_in` — the only online way to ask "which airport contains this point" — is
frequently unavailable.  So airports are resolved from a bundled subset of the
public-domain OurAirports dataset (large + medium fields) via point-in-radius.
No network call → reliable.

Public API:
    nearest_airport(lat, lon) -> dict | None
"""

import json
import math
import os
from functools import lru_cache

_DATA_PATH = os.path.join(os.path.dirname(__file__), "data", "airports.json")

# Max distance (km) from the gazetteer reference point to still count as being
# "inside" the airport.  Large hubs sprawl several km from their centroid;
# medium fields are tighter.  Airports sit far apart, so generous radii rarely
# collide — and when they could, the nearest one wins.
_RADIUS_KM = {"large": 6.0, "medium": 3.5}


@lru_cache(maxsize=1)
def _airports() -> list[dict]:
    with open(_DATA_PATH, encoding="utf-8") as f:
        return json.load(f)


def _haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    R = 6371.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlam = math.radians(lon2 - lon1)
    a = math.sin(dphi / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dlam / 2) ** 2
    return 2 * R * math.asin(math.sqrt(a))


def nearest_airport(lat: float, lon: float) -> dict | None:
    """
    Return the airport whose footprint contains this point, or None.

    A coarse lat/lon box prefilter (~16 km) skips the haversine for all but a
    handful of candidates, so the full-table scan stays cheap per call.
    """
    best: dict | None = None
    best_d: float | None = None
    for a in _airports():
        if abs(a["lat"] - lat) > 0.15 or abs(a["lon"] - lon) > 0.2:
            continue
        d = _haversine_km(lat, lon, a["lat"], a["lon"])
        if d <= _RADIUS_KM.get(a["type"], 3.5) and (best_d is None or d < best_d):
            best, best_d = a, d
    return best

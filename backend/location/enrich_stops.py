"""
enrich_stops.py
---------------
Geocode GPS segments using:
  1. Nominatim (zoom=18 + extratags)  — POI name + Wikidata QID for stop segments
  2. Wikidata                          — description + P31 type labels
  3. Nominatim (zoom=10)               — city-level clusters for move "A → B" names

Public API:
    enrich_stop(lat, lon)                       → dict
    enrich_move(gps_pts, fallback_lat, fallback_lon) → dict
"""

import logging
import time

import numpy as np
import requests
from sklearn.cluster import DBSCAN

logger = logging.getLogger(__name__)

_HEADERS = {"User-Agent": "lifelog-picam/1.0"}

# ─── Country code table ───────────────────────────────────────────────────────

_CC = {
    "IE": "Ireland", "GB": "United Kingdom", "US": "United States",
    "FR": "France", "DE": "Germany", "ES": "Spain", "IT": "Italy",
    "NL": "Netherlands", "BE": "Belgium", "PT": "Portugal",
    "PL": "Poland", "SE": "Sweden", "NO": "Norway", "DK": "Denmark",
    "FI": "Finland", "CH": "Switzerland", "AT": "Austria",
    "CZ": "Czech Republic", "HU": "Hungary", "RO": "Romania",
    "CN": "China", "JP": "Japan", "KR": "South Korea",
    "AU": "Australia", "CA": "Canada", "BR": "Brazil",
    "IN": "India", "ZA": "South Africa", "MX": "Mexico", "AR": "Argentina",
    "VN": "Vietnam", "TH": "Thailand", "SG": "Singapore",
}

# In Nominatim's address dict, the value under these keys IS the place name
# (e.g. address.amenity = "Starbucks", not "cafe")
_POI_ADDR_KEYS = [
    "amenity", "shop", "tourism", "leisure", "office",
    "historic", "healthcare", "public_transport",
]

# Sub-city fields checked in priority order for suburb/neighbourhood extraction
_SUBURB_KEYS = (
    "suburb", "neighbourhood", "neighborhood",
    "quarter", "city_district", "district", "borough",
)

# ─── Nominatim ────────────────────────────────────────────────────────────────

_NOM_URL = "https://nominatim.openstreetmap.org/reverse"
_NOM_RATE = 1.1   # seconds between requests (Nominatim policy: max 1 req/s)
_last_nom: float = 0.0
_nom_cache: dict = {}


def nominatim_reverse(lat: float, lon: float, zoom: int = 14, extratags: bool = False) -> dict:
    """Rate-limited Nominatim reverse geocode. Returns raw JSON dict or {}."""
    global _last_nom
    cache_key = (round(lat, 2), round(lon, 2), zoom, extratags)
    if cache_key in _nom_cache:
        return _nom_cache[cache_key]

    wait = _NOM_RATE - (time.monotonic() - _last_nom)
    if wait > 0:
        time.sleep(wait)

    params: dict = {
        "lat": lat, "lon": lon, "format": "json",
        "zoom": zoom, "addressdetails": 1,
    }
    if extratags:
        params["extratags"] = 1

    try:
        r = requests.get(_NOM_URL, params=params, headers=_HEADERS, timeout=10)
        r.raise_for_status()
        raw = r.json()
        _last_nom = time.monotonic()
    except Exception as exc:
        logger.warning("Nominatim error at (%.5f, %.5f): %s", lat, lon, exc)
        return {}

    _nom_cache[cache_key] = raw
    return raw


def _parse_admin(raw: dict) -> dict:
    """Extract full admin hierarchy from a Nominatim response."""
    addr = raw.get("address", {})
    cc = addr.get("country_code", "").upper()
    country = _CC.get(cc, addr.get("country", cc))
    city = next(
        (addr[k] for k in ("city", "town", "village", "municipality", "county") if addr.get(k)),
        "",
    )
    state = next(
        (addr[k] for k in ("state", "region", "province", "state_district") if addr.get(k)),
        "",
    )
    suburb = next((addr[k] for k in _SUBURB_KEYS if addr.get(k)), "")
    postcode = addr.get("postcode", "")
    return {
        "city": city,
        "suburb": suburb,
        "state": state,    # state/province, stored as Location.region
        "region": [v for v in [city, state, country] if v],  # breadcrumb list (internal)
        "country": country,
        "postcode": postcode,
    }


# ─── Wikidata ─────────────────────────────────────────────────────────────────

_WD_API = "https://www.wikidata.org/w/api.php"
_wd_cache: dict[str, dict] = {}

# Common P31 (instance-of) QIDs → human label; unknown QIDs pass through as-is
_P31_LABELS: dict[str, str] = {
    "Q11707": "restaurant", "Q965747": "cafe", "Q187456": "bar",
    "Q570116": "tourist attraction", "Q33506": "museum",
    "Q16917": "hospital", "Q3914": "school", "Q3918": "university",
    "Q174782": "marketplace", "Q7075": "library", "Q41253": "cinema",
    "Q8187769": "gym", "Q27686": "hotel", "Q2360219": "hostel",
    "Q105837": "pharmacy", "Q1616075": "train station",
    "Q928830": "metro station", "Q1078765": "airport terminal",
    "Q44665": "airport", "Q22698": "park",
}


def wikidata_fetch(qid: str) -> dict:
    """
    Fetch English label, description, and P31 (instance-of) types for a QID.
    Returns {} on error.
    """
    if qid in _wd_cache:
        return _wd_cache[qid]
    try:
        r = requests.get(
            _WD_API,
            params={
                "action": "wbgetentities", "ids": qid,
                "props": "labels|descriptions|claims",
                "languages": "en", "format": "json",
            },
            headers=_HEADERS,
            timeout=10,
        )
        r.raise_for_status()
        entity = r.json().get("entities", {}).get(qid, {})
    except Exception as exc:
        logger.warning("Wikidata error for %s: %s", qid, exc)
        _wd_cache[qid] = {}
        return {}

    label = entity.get("labels", {}).get("en", {}).get("value", "")
    description = entity.get("descriptions", {}).get("en", {}).get("value", "")
    p31_qids = [
        c["mainsnak"]["datavalue"]["value"]["id"]
        for c in entity.get("claims", {}).get("P31", [])
        if c.get("mainsnak", {}).get("datavalue")
    ]
    instance_of = [_P31_LABELS.get(q, q) for q in p31_qids]

    result = {"label": label, "description": description, "instance_of": instance_of}
    _wd_cache[qid] = result
    return result


# ─── Move segment helpers ─────────────────────────────────────────────────────

_MOVE_EPS = 5.0 / 6371.0   # ~5 km in radians
_MOVE_MIN_PTS = 3


def _cluster_points_by_city(
    points: list[tuple[float, float]],
) -> list[tuple[float, float]]:
    """
    DBSCAN over GPS points with a ~5 km radius.
    Returns one median representative per cluster, in order.
    """
    if not points:
        return []
    if len(points) < _MOVE_MIN_PTS:
        arr = np.array(points)
        med = np.median(arr, axis=0)
        return [(float(med[0]), float(med[1]))]

    arr = np.radians(np.array(points))
    labels = DBSCAN(
        eps=_MOVE_EPS, min_samples=_MOVE_MIN_PTS,
        algorithm="ball_tree", metric="haversine",
    ).fit_predict(arr)

    pts_arr = np.array(points)
    representatives = []
    for cl in sorted(set(labels)):
        mask = labels == cl
        med = np.median(pts_arr[mask], axis=0)
        representatives.append((float(med[0]), float(med[1])))
    return representatives


def _extract_suburb(raw: dict) -> str:
    """Return the most specific sub-city area name from a Nominatim response."""
    addr = raw.get("address", {})
    return next((addr[k] for k in _SUBURB_KEYS if addr.get(k)), "")


# ─── Shared empty result ──────────────────────────────────────────────────────

_EMPTY: dict = {
    "name": "", "wikidata_id": "", "osm_type": "", "osm_id": "",
    "description": "", "categories": [],
    "city": "", "suburb": "", "region": "", "country": "",
    "postcode": "", "address": "",
}

# ─── Public API ───────────────────────────────────────────────────────────────


def enrich_stop(lat: float, lon: float) -> dict:
    """
    Reverse-geocode a stop centroid.

    Uses Nominatim at zoom=18 with extratags to get:
      - POI name from address components (e.g. address.amenity = "Starbucks")
      - Wikidata QID from extratags.wikidata (if tagged in OSM)
      - OSM category from extratags (e.g. extratags.amenity = "cafe")
      - Admin hierarchy (city / region / country)

    If a Wikidata QID is found, enriches with P31 types and description.
    """
    raw = nominatim_reverse(lat, lon, zoom=18, extratags=True)
    if not raw:
        return _EMPTY.copy()

    addr = raw.get("address", {})
    extratags = raw.get("extratags", {}) or {}

    # POI name: Nominatim puts the place name as the value under the category key
    name = next((addr[k] for k in _POI_ADDR_KEYS if addr.get(k)), "")

    # OSM category types (the type string, e.g. "cafe", "supermarket")
    osm_cats = [extratags[k] for k in _POI_ADDR_KEYS if extratags.get(k)]

    wikidata_id = extratags.get("wikidata", "")
    description = ""
    instance_of: list[str] = []

    if wikidata_id:
        wd = wikidata_fetch(wikidata_id)
        if not name and wd.get("label"):
            name = wd["label"]
        description = wd.get("description", "")
        instance_of = wd.get("instance_of", [])

    categories = list(dict.fromkeys(osm_cats + instance_of))
    admin = _parse_admin(raw)

    return {
        "name": name,
        "wikidata_id": wikidata_id,
        "osm_type": raw.get("osm_type", ""),
        "osm_id": str(raw.get("osm_id", "")),
        "description": description,
        "categories": categories,
        "city": admin["city"],
        "suburb": admin["suburb"],
        "region": admin["state"],      # state/province as a string
        "country": admin["country"],
        "postcode": admin["postcode"],
        "address": raw.get("display_name", ""),
    }


def enrich_move(
    gps_pts: list[tuple[float, float]],
    fallback_lat: float | None = None,
    fallback_lon: float | None = None,
) -> dict:
    """
    Reverse-geocode a move segment.

    1. Clusters GPS track points into ~5 km city-groups (Nominatim zoom=10).
    2. Multi-city move  → "City A → City B"
    3. Single-city move → suburb/neighbourhood of start and end points at zoom=14,
                          giving "Rathmines → City Centre" instead of "Dublin → Dublin".
    """
    if not gps_pts:
        if fallback_lat is not None and fallback_lon is not None:
            gps_pts = [(fallback_lat, fallback_lon)]
        else:
            return _EMPTY.copy()

    representatives = _cluster_points_by_city(gps_pts)

    city_entries: list[dict] = []
    seen_cities: set[tuple] = set()
    for rlat, rlon in representatives:
        raw = nominatim_reverse(rlat, rlon, zoom=10)
        admin = _parse_admin(raw)
        city = admin.get("city", "")
        country = admin.get("country", "")
        dedup_key = (city.lower(), country.lower())
        if city and dedup_key not in seen_cities:
            seen_cities.add(dedup_key)
            city_entries.append(admin)

    if not city_entries:
        return _EMPTY.copy()

    all_states = list(dict.fromkeys(e["state"] for e in city_entries if e.get("state")))
    all_countries = list(dict.fromkeys(e["country"] for e in city_entries if e.get("country")))
    country_val = all_countries[0] if len(all_countries) == 1 else ", ".join(all_countries)
    region_val = all_states[0] if len(all_states) == 1 else ", ".join(all_states)

    if len(city_entries) > 1:
        # Multi-city move: "Dublin → Galway"
        name = " → ".join(e["city"] for e in city_entries if e.get("city"))
        city_val = name
        suburb_val = ""
    else:
        # Single-city move: try suburb-level for start and end points
        city_val = city_entries[0]["city"]
        start_raw = nominatim_reverse(gps_pts[0][0], gps_pts[0][1], zoom=14)
        end_raw = nominatim_reverse(gps_pts[-1][0], gps_pts[-1][1], zoom=14)
        start_sub = _extract_suburb(start_raw)
        end_sub = _extract_suburb(end_raw)
        suburb_val = start_sub or end_sub

        if start_sub and end_sub and start_sub != end_sub:
            name = f"{start_sub} → {end_sub}"
        elif start_sub or end_sub:
            name = start_sub or end_sub
        else:
            name = city_val  # last resort: just the city name

    return {
        "name": name,
        "wikidata_id": "",
        "osm_type": "",
        "osm_id": "",
        "description": "",
        "categories": [],
        "city": city_val,
        "suburb": suburb_val,
        "region": region_val,
        "country": country_val,
        "postcode": "",
        "address": "",
    }

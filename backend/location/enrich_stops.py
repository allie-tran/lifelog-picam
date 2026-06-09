"""
enrich_stops.py
---------------
Geocode GPS segments using three open data sources:
  1. Overpass API  — find nearby OSM POIs within a radius (stop segments only)
  2. Wikidata      — enrich OSM elements that carry a `wikidata=Q...` tag
  3. Nominatim     — resolve admin hierarchy (city / region / country)

Called from Step 8 of gps_pipeline.run_pipeline().
"""

import logging
import time

import requests

logger = logging.getLogger(__name__)

_HEADERS = {"User-Agent": "lifelog-picam/1.0"}

# ─── Country code → name ──────────────────────────────────────────────────────

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

# OSM tag keys checked for POI type, in priority order
_OSM_POI_KEYS = [
    "amenity", "shop", "tourism", "leisure", "office",
    "historic", "healthcare", "public_transport",
]

# ─── Helpers ──────────────────────────────────────────────────────────────────

def _haversine(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Great-circle distance in metres."""
    import math
    R = 6_371_000
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlam = math.radians(lon2 - lon1)
    a = math.sin(dphi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(dlam / 2) ** 2
    return 2 * R * math.asin(math.sqrt(a))


# ─── Overpass API ─────────────────────────────────────────────────────────────

_OVERPASS_URL = "https://overpass-api.de/api/interpreter"
_STOP_RADIUS = 200  # metres

def overpass_nearby(lat: float, lon: float, radius: int = _STOP_RADIUS) -> list[dict]:
    """
    Query OSM for POIs within `radius` metres of (lat, lon).
    Returns a list of dicts sorted by distance (closest first), each with:
        osm_type, osm_id, name, tags, distance, wikidata_id
    """
    filters = "\n  ".join(
        f'node["{k}"](around:{radius},{lat:.6f},{lon:.6f});\n  way["{k}"](around:{radius},{lat:.6f},{lon:.6f});'
        for k in _OSM_POI_KEYS
    )
    query = f"[out:json][timeout:20];\n(\n  {filters}\n);\nout center tags;"
    try:
        r = requests.post(_OVERPASS_URL, data={"data": query}, headers=_HEADERS, timeout=25)
        r.raise_for_status()
        elements = r.json().get("elements", [])
    except Exception as exc:
        logger.warning("Overpass error at (%.5f, %.5f): %s", lat, lon, exc)
        return []

    results = []
    for el in elements:
        tags = el.get("tags", {})
        if not tags.get("name"):
            continue  # unnamed elements aren't useful as stop labels
        if el["type"] == "way":
            c = el.get("center", {})
            elat, elon = c.get("lat", lat), c.get("lon", lon)
        else:
            elat, elon = el.get("lat", lat), el.get("lon", lon)
        results.append({
            "osm_type": el["type"],
            "osm_id": str(el["id"]),
            "name": tags["name"],
            "tags": tags,
            "distance": _haversine(lat, lon, elat, elon),
            "wikidata_id": tags.get("wikidata", ""),
        })

    results.sort(key=lambda x: x["distance"])
    return results


# ─── Wikidata API ─────────────────────────────────────────────────────────────

_WD_API = "https://www.wikidata.org/w/api.php"
_wd_cache: dict[str, dict] = {}

# P31 QID → human-readable category (common values; others fall through as QIDs)
_P31_LABELS = {
    "Q11707": "restaurant", "Q965747": "cafe", "Q187456": "bar",
    "Q570116": "tourist attraction", "Q33506": "museum",
    "Q16917": "hospital", "Q3914": "school", "Q3918": "university",
    "Q174782": "marketplace", "Q7075": "library", "Q41253": "cinema",
    "Q8187769": "gym", "Q27686": "hotel", "Q2360219": "hostel",
    "Q105837": "pharmacy", "Q1616075": "train station",
    "Q928830": "metro station", "Q1078765": "airport terminal",
    "Q44665": "airport", "Q490": "subway", "Q12280": "bridge",
    "Q35127": "website", "Q2516866": "park", "Q22698": "park",
}


def wikidata_fetch(qid: str) -> dict:
    """
    Fetch the English label, description, and P31 (instance-of) types for a QID.
    Returns {} on error.
    """
    if qid in _wd_cache:
        return _wd_cache[qid]
    try:
        r = requests.get(
            _WD_API,
            params={
                "action": "wbgetentities",
                "ids": qid,
                "props": "labels|descriptions|claims",
                "languages": "en",
                "format": "json",
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
    p31_claims = entity.get("claims", {}).get("P31", [])
    instance_of_qids = [
        c["mainsnak"]["datavalue"]["value"]["id"]
        for c in p31_claims
        if c.get("mainsnak", {}).get("datavalue")
    ]
    instance_of = [_P31_LABELS.get(q, q) for q in instance_of_qids]

    result = {"label": label, "description": description, "instance_of": instance_of}
    _wd_cache[qid] = result
    return result


# ─── Nominatim ────────────────────────────────────────────────────────────────

_NOM_URL = "https://nominatim.openstreetmap.org/reverse"
_NOM_RATE = 1.1  # seconds between requests (policy: max 1 req/s)
_last_nom: float = 0.0
_nom_cache: dict[tuple, dict] = {}


def nominatim_reverse(lat: float, lon: float, zoom: int = 14) -> dict:
    """
    Reverse geocode for admin hierarchy. Rate-limited to Nominatim policy.
    zoom=14 = city level; zoom=18 = building level.
    Returns the raw Nominatim JSON dict, or {} on error.
    """
    global _last_nom
    key = (round(lat, 2), round(lon, 2), zoom)
    if key in _nom_cache:
        return _nom_cache[key]

    wait = _NOM_RATE - (time.monotonic() - _last_nom)
    if wait > 0:
        time.sleep(wait)
    try:
        r = requests.get(
            _NOM_URL,
            params={"lat": lat, "lon": lon, "format": "json", "zoom": zoom, "addressdetails": 1},
            headers=_HEADERS,
            timeout=10,
        )
        r.raise_for_status()
        raw = r.json()
        _last_nom = time.monotonic()
    except Exception as exc:
        logger.warning("Nominatim error at (%.5f, %.5f): %s", lat, lon, exc)
        return {}

    _nom_cache[key] = raw
    return raw


def _parse_admin(raw: dict) -> dict:
    """Extract city / region / country from a Nominatim response."""
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
    region = [v for v in [city, state, country] if v]
    return {"city": city, "region": region, "country": country}


# ─── Main entry point ─────────────────────────────────────────────────────────

# _EMPTY: dict = {
#     "name": "", "wikidata_id": "", "osm_type": "", "osm_id": "",
#     "description": "", "categories": [],
#     "city": "", "region": [], "country": "", "address": "",
# }

_EMPTY: dict = {
    "name": "",
    "fsq_id": "",
    "info": "",
    "country": "",
    "address": "",
    "latitude": None,
    "longitude": None,
}


def enrich_segment(lat: float, lon: float, is_stop: bool) -> dict | None:
    """
    Enrich a segment centroid.

    For stops:
      - Overpass → ranked list of nearby named OSM POIs
      - Wikidata → label, description, type (if the best OSM match has a wikidata tag)
      - Nominatim → city / region / country

    For moves:
      - Nominatim only (city zoom)

    Returns dict with keys:
        name, wikidata_id, osm_type, osm_id, description, categories,
        city, region, country, address
    """
    # Admin hierarchy: always Nominatim
    nom = nominatim_reverse(lat, lon, zoom=18)
    admin = _parse_admin(nom)
    address = nom.get("display_name", "")

    return {
        **_EMPTY,
        "name": address.split(",")[0] if address else "",
        "country": admin["country"],
        "address": address,
        "latitude": float(lat),
        "longitude": float(lon),
        "key": f"stop={is_stop},{address}",
    }

    if not is_stop:
        return {
            **_EMPTY,
            "country": admin["country"],
            "address": address,
            "latitude": float(lat),
            "longitude": float(lon),
            "key": f"{admin['country']}|{admin['region']}|{admin['city']}",
        }
        # return {**_EMPTY, **admin, "address": address}

    # Stop: find nearby POIs via Overpass
    candidates = overpass_nearby(lat, lon)
    if not candidates:
        return {
            **_EMPTY,
            "country": admin["country"],
            "address": address,
            "latitude": float(lat),
            "longitude": float(lon),
            "key": f"{admin['country']}|{admin['region']}|{admin['city']}",
        }

    best = candidates[0]  # closest named POI
    name = best["name"]
    wikidata_id = best["wikidata_id"]
    description = ""
    instance_of: list[str] = []

    # Enrich with Wikidata when we have a QID
    if wikidata_id:
        wd = wikidata_fetch(wikidata_id)
        if not name and wd.get("label"):
            name = wd["label"]
        description = wd.get("description", "")
        instance_of = wd.get("instance_of", [])

    # Build category list: OSM tag values + Wikidata P31 types
    tags = best["tags"]
    osm_cats = [tags[k] for k in _OSM_POI_KEYS if k in tags]
    categories = list(dict.fromkeys(osm_cats + instance_of))  # deduped, order-preserving

    return {
        "name": name,
        "fsq_id": f"wiki_{wikidata_id}" if wikidata_id else f"osm_{best['osm_type'][0]}{best['osm_id']}",
        "info": f"{categories}, {description}".strip(", "),
        "country": admin["country"],
        "address": address,
        "latitude": float(lat),
        "longitude": float(lon),
        "key": f"{name}|{admin['country']}|{address}",
    }

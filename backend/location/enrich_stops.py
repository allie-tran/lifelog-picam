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

from location.airports import nearest_airport

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
# (e.g. address.amenity = "Starbucks", not "cafe"; address.aeroway = "Dublin Airport")
_POI_ADDR_KEYS = [
    "amenity", "shop", "tourism", "leisure", "office",
    "historic", "healthcare", "public_transport", "aeroway",
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

# ─── Overpass ─────────────────────────────────────────────────────────────────

_OVERPASS_URL = "https://overpass-api.de/api/interpreter"
_OVERPASS_RATE = 2.0
_last_overpass: float = 0.0
_overpass_cache: dict[tuple, str] = {}

# Nominatim OSM classes that indicate a non-POI result — road, bench, boundary, etc.
_NON_POI_CLASSES = {"highway", "boundary", "waterway", "natural", "place"}

# Classes worth adopting as a stop's identity when the fine (zoom=18) result is
# just a road/parking inside a big named venue — airport, campus, park, mall.
_AREA_CLASSES = {"aeroway", "amenity", "leisure", "tourism", "historic", "landuse", "military"}

# Tags searched by Overpass in priority order (first match wins)
_OVERPASS_QUERY_TMPL = """[out:json][timeout:10];
is_in({lat},{lon})->.a;
(
  way(pivot.a)[name][amenity~"university|college|school|hospital|clinic|library|theatre|cinema|marketplace|community_centre|arts_centre"];
  way(pivot.a)[name][leisure~"sports_centre|stadium|park|golf_course|ice_rink|swimming_pool"];
  way(pivot.a)[name][tourism~"hotel|museum|attraction|gallery|theme_park|zoo"];
  way(pivot.a)[name][landuse~"education|commercial|retail|industrial|military|religious"];
  way(pivot.a)[name][aeroway~"aerodrome|terminal"];
  relation(pivot.a)[name][amenity~"university|college|school|hospital"];
  relation(pivot.a)[name][aeroway~"aerodrome|terminal"];
);
out 5;"""


def overpass_named_place(lat: float, lon: float) -> str:
    """
    Find the named POI area that actually contains this point.
    Uses is_in — only matches if the point is geometrically inside the polygon.
    Returns the place name string, or "" if not inside any known POI area.
    """
    global _last_overpass
    cache_key = (round(lat, 4), round(lon, 4))
    if cache_key in _overpass_cache:
        return _overpass_cache[cache_key]

    wait = _OVERPASS_RATE - (time.monotonic() - _last_overpass)
    if wait > 0:
        time.sleep(wait)

    query = _OVERPASS_QUERY_TMPL.format(lat=lat, lon=lon)
    try:
        r = requests.post(_OVERPASS_URL, data={"data": query}, headers=_HEADERS, timeout=15)
        r.raise_for_status()
        elements = r.json().get("elements", [])
        _last_overpass = time.monotonic()
    except Exception as exc:
        logger.warning("Overpass error at (%.5f, %.5f): %s", lat, lon, exc)
        _overpass_cache[cache_key] = ""
        return ""

    name = ""
    for el in elements:
        n = el.get("tags", {}).get("name", "")
        if n:
            name = n
            break

    _overpass_cache[cache_key] = name
    return name


def nominatim_reverse(lat: float, lon: float, zoom: int = 14, extratags: bool = False) -> dict:
    """Rate-limited Nominatim reverse geocode. Returns raw JSON dict or {}."""
    global _last_nom
    if zoom > 18:
        zoom = 18

    # rounding based on zoom level
    if zoom <= 10:
        lat = round(lat, 2)
        lon = round(lon, 2)
    elif zoom <= 14:
        lat = round(lat, 3)
        lon = round(lon, 3)
    else:
        lat = round(lat, 5)
        lon = round(lon, 5)

    cache_key = (lat, lon, zoom, extratags)
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


def _enclosing_area(lat: float, lon: float) -> dict:
    """
    Find the large named feature that *contains* this point by reverse-geocoding
    at progressively coarser zoom.  Nominatim returns the smallest feature at a
    given zoom, so stepping 16→14→12 climbs out of a taxiway/parking aisle onto
    the enclosing aerodrome / campus / park polygon — carrying that polygon's own
    name, OSM id and Wikidata tag.

    Returns the raw Nominatim dict for the area, or {} if no named area is found.
    Nominatim-only — does NOT depend on Overpass (which is frequently down).
    """
    for z in (16, 14):
        raw = nominatim_reverse(lat, lon, zoom=z, extratags=True)
        if not raw:
            continue
        if raw.get("name", "") and raw.get("class", "") in _AREA_CLASSES:
            return raw
    return {}


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


def _poi_only_geo(poi: dict) -> dict:
    """Build a geo dict from a gazetteer POI alone (Nominatim returned nothing)."""
    geo = _EMPTY.copy()
    geo.update({
        "name": poi.get("name", ""),
        "wikidata_id": poi.get("wikidata_id", ""),
        "osm_type": poi.get("osm_type", ""),
        "osm_id": str(poi.get("osm_id", "")),
        "categories": [poi["category"]] if poi.get("category") else [],
    })
    return geo


def enrich_stop(lat: float, lon: float, poi: dict | None = None) -> dict:
    """
    Reverse-geocode a stop centroid.

    Uses Nominatim at zoom=18 with extratags to get:
      - POI name from address components (e.g. address.amenity = "Starbucks")
      - Wikidata QID from extratags.wikidata (if tagged in OSM)
      - OSM category from extratags (e.g. extratags.amenity = "cafe")
      - Admin hierarchy (city / region / country)

    If a Wikidata QID is found, enriches with P31 types and description.

    ``poi`` — an optional venue chosen by visual disambiguation
    (``poi_gazetteer.disambiguate_poi``). When supplied it overrides the venue
    *identity* (name, category, OSM/Wikidata provenance) so a centroid that
    drifted onto the wrong storefront is corrected; the admin hierarchy still
    comes from Nominatim. Geocoding is otherwise unchanged.
    """
    raw = nominatim_reverse(lat, lon, zoom=18, extratags=True)
    if not raw:
        if poi:
            return _poi_only_geo(poi)
        return _EMPTY.copy()

    addr = raw.get("address", {})
    extratags = raw.get("extratags", {}) or {}

    # 1. OSM element's own name tag — most reliable for named POIs and buildings
    name = raw.get("name", "")

    # 2. Address category keys (e.g. addr.amenity = "Starbucks").
    #    Skip generic type strings that aren't proper names ("yes", "company", etc.)
    _GENERIC = {"yes", "no", "company", "residential", "office", "building", "house"}
    if not name:
        for k in _POI_ADDR_KEYS:
            v = addr.get(k, "")
            if v and v.lower() not in _GENERIC:
                name = v
                break

    # 3. Fine (zoom=18) result is a road / boundary / nameless point inside a
    #    larger venue.  Resolve that venue WITHOUT leaning on Overpass (down ~half
    #    the time), in order of reliability:
    #      a. Airport gazetteer — offline point-in-radius, no network.  Nominatim
    #         never returns the aerodrome polygon (it gives an unnamed aeroway
    #         node / taxiway / admin boundary), so this is the only reliable path
    #         for the common "I'm in an airport" case.
    #      b. Coarser Nominatim zoom — catches some campuses / parks.
    #      c. Overpass `is_in` — best-effort last resort.
    #    Adopting the venue's identity (name + a stable id) also makes every stop
    #    fragment inside one big venue dedup to a single Location downstream,
    #    instead of scattering one marker per gate/aisle.
    airport: dict | None = None
    if not name or raw.get("class") in _NON_POI_CLASSES:
        airport = nearest_airport(lat, lon)
        if airport:
            name = airport["name"]
        else:
            area = _enclosing_area(lat, lon)
            if area.get("name"):
                raw = area
                addr = raw.get("address", {})
                extratags = raw.get("extratags", {}) or {}
                name = raw["name"]
            else:
                overpass_name = overpass_named_place(lat, lon)
                if overpass_name:
                    name = overpass_name

    # 4. Last resort: street address
    if not name:
        road = addr.get("road", "")
        name = str(road) # No house number.

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

    # A gazetteer airport overrides OSM provenance with a stable synthetic id
    # (its ICAO/ident). Keying on this downstream collapses every stop fragment
    # inside the airport into one Location instead of scattering road markers.
    if airport:
        osm_type, osm_id = "airport", airport["id"]
        categories = list(dict.fromkeys(["airport"] + categories))
    else:
        osm_type, osm_id = raw.get("osm_type", ""), str(raw.get("osm_id", ""))

    # Visual disambiguation override: the chosen venue replaces the geocoder's
    # identity (name / category / provenance), keeping Nominatim's admin
    # hierarchy. Skipped inside an airport, where the gazetteer footprint wins.
    if poi and not airport:
        name = poi.get("name") or name
        if poi.get("category"):
            categories = list(dict.fromkeys([poi["category"]] + categories))
        osm_type, osm_id = poi["osm_type"], str(poi["osm_id"])
        if poi.get("wikidata_id") and poi["wikidata_id"] != wikidata_id:
            wikidata_id = poi["wikidata_id"]
            wd = wikidata_fetch(wikidata_id)
            description = wd.get("description", "") or description
            if wd.get("instance_of"):
                categories = list(dict.fromkeys(categories + wd["instance_of"]))

    return {
        "name": name,
        "wikidata_id": wikidata_id,
        "osm_type": osm_type,
        "osm_id": osm_id,
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

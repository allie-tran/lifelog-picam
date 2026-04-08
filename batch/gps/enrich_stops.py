"""
enrich_stops.py
---------------
Takes segments.csv (output of gps_pipeline.py), finds images for each stop
segment from MongoDB, loads CLIP features, queries Foursquare for nearby
places, scores them with CLIP text similarity, and writes semantic_stops.csv.

Dependencies:
    pip install pymongo gpxpy scikit-learn pandas numpy tqdm requests
    pip install torch clip-by-openai   # or your local CLIP install
"""

import hashlib
import json
import os
import re
import time
from timezonefinder import TimezoneFinder


import clip
import numpy as np
import pandas as pd
import torch
from dotenv import load_dotenv
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session
from tqdm.auto import tqdm
from unidecode import unidecode

from annotate_images import load_model
from models import CLIPEmbedding, Image, ImageEmbedding

load_dotenv()

# ─── Config ───────────────────────────────────────────────────────────────────
SEGMENTS_FILE = "files/segments.csv"
GPS_FILE = "files/image_gps.csv"
OUTPUT_FILE = "files/nominatim_semantic_stops.csv"
CACHE_DIR = "cached"

FSQ_API_KEY = os.environ.get("FSQ_API_KEY", "")  # set in environment
assert FSQ_API_KEY, "FSQ_API_KEY not set in environment variables"
FSQ_NEARBY_URL = "https://places-api.foursquare.com/geotagging/candidates"
FSQ_DETAILS_URL = "https://places-api.foursquare.com/places/{fsq_id}"
FSQ_PHOTOS_URL = "https://places-api.foursquare.com/places/{fsq_id}/photos"

DISTANCE_THRESHOLD = 200  # metres — hard-coded home detection radius
HOME_LAT, HOME_LON = 53.38998, -6.14576
WORK_LAT, WORK_LON = 53.3853317, -6.2588403

CUDA = torch.cuda.is_available()
DEVICE = "cuda" if CUDA else "cpu"

PG_URI = os.environ.get("PG_URI", "postgresql://postgres:password@localhost:5432/lifelog")
engine = create_engine(PG_URI)
session = Session(bind=engine.connect())


# ─── Cache helpers ────────────────────────────────────────────────────────────

os.makedirs(CACHE_DIR, exist_ok=True)

def _cache_path(key: str) -> str:
    h = hashlib.md5(key.encode()).hexdigest()
    return os.path.join(CACHE_DIR, f"{h}.json")


def cache_get(key: str):
    p = _cache_path(key)
    if os.path.exists(p):
        with open(p) as f:
            return json.load(f)
    return None


def cache_set(key: str, value):
    p = _cache_path(key)
    with open(p, "w") as f:
        json.dump(value, f, default=str)


# ─── Foursquare API ───────────────────────────────────────────────────────────

FSQ_HEADERS = {
    "accept": "application/json",
    "authorization": f"Bearer {FSQ_API_KEY}",
    "X-Places-Api-Version": "2025-06-17",
}

import requests


def _fsq_get(url, params=None, retries=3, backoff=2.0):
    """Thin wrapper with retry + backoff."""
    for attempt in range(retries):
        try:
            r = requests.get(url, headers=FSQ_HEADERS, params=params, timeout=10)
            r.raise_for_status()
            return r.json()
        except Exception as e:
            if attempt == retries - 1:
                print(f"  FSQ error {url}: {e}")
                curl = f"curl --request GET '{url}' --header 'accept: application/json' --header 'authorization: Bearer {FSQ_API_KEY}' --header 'X-Places-Api-Version: 2025-06-17'"
                if params:
                    param_str = " \\\n  ".join(
                        [f"--data-urlencode '{k}={v}'" for k, v in params.items()]
                    )
                    curl += " \\\n  " + param_str
                print(f"  cURL: {curl}")
                return {}
            time.sleep(backoff * (attempt + 1))
    return {}


def get_nearby_places(lat: float, lon: float, altitude: float) -> list[dict]:
    lat = round(lat, 4)
    lon = round(lon, 4)
    # round altitude to nearest 5m to avoid excessive cache fragmentation
    altitude = (round(altitude / 5) * 5) if altitude is not None else None
    key = f"nearby_{lat}_{lon}_{altitude}"
    cached = cache_get(key)
    if cached is not None:
        return cached
    data = _fsq_get(
        FSQ_NEARBY_URL,
        params={
            "ll": f"{lat},{lon}",
            "altitude": altitude,
            "limit": 20,
            "fields": "fsq_place_id,name,latitude,longitude,location,categories,related_places,distance",
        },
    )
    results = data.get("candidates", [])
    cache_set(key, results)
    return results


def get_place_details(fsq_id: str) -> dict:
    key = f"details_{fsq_id}"
    cached = cache_get(key)
    if cached is not None:
        return cached
    data = _fsq_get(
        FSQ_DETAILS_URL.format(fsq_id=fsq_id),
        params={
            "fields": "fsq_place_id,name,latitude,longitude,location,categories,related_places,distance"
        },
    )
    cache_set(key, data)
    return data


def parse_place(raw: dict) -> dict:
    """Normalise a raw FSQ place dict into a flat checkin-style dict."""
    cats = [c["name"] for c in raw.get("categories", [])]
    related = raw.get("related_places", {})
    parent = related.get("parent", {})
    return {
        "name": raw.get("name", "Unknown Place"),
        "fsq_place_id": raw.get("fsq_place_id", ""),
        "latitude": raw.get("latitude", 0.0),
        "longitude": raw.get("longitude", 0.0),
        "location": raw.get("location", {}),
        "categories": cats,
        "parent": parent.get("name", ""),
        "parent_id": parent.get("fsq_place_id", ""),
        "distance": raw.get("distance", 0.0),
    }


def detect_airport(place: dict) -> bool:
    cats = ", ".join(place["categories"]).lower()
    return (
        "airport" in cats
        or "airport" in place["name"].lower()
        or "airport" in place["parent"].lower()
    )


def expand_with_parents(places: list[dict], distance_threshold: int) -> list[dict]:
    """
    For each place, if it has a parent not yet in the list, fetch and add it.
    Also walks up the hierarchy for airports.
    """
    seen_ids = {p["fsq_place_id"] for p in places}
    extra = []
    for place in list(places):
        # Airport hierarchy walk
        if detect_airport(place) and place["parent_id"]:
            pid = place["parent_id"]
            for _ in range(5):
                if not pid:
                    break
                details = get_place_details(pid)
                related = details.get("related_places", {})
                if "parent" in related:
                    place["parent"] = related["parent"]["name"]
                    place["parent_id"] = related["parent"]["fsq_place_id"]
                    pid = place["parent_id"]
                else:
                    break

        # Add parent as its own candidate
        if (
            place["parent_id"]
            and place["parent_id"] not in seen_ids
            and place["parent"] != place["name"]
        ):
            details = get_place_details(place["parent_id"])
            parent_place = parse_place({**details, "fsq_place_id": place["parent_id"]})
            seen_ids.add(place["parent_id"])
            extra.append(parent_place)

    return places + extra


# ─── Nominatim ────────────────────────────────────────────────────────────────

_last_request = 0.0
RATE_LIMIT = 1.0  # seconds between requests to respect Nominatim usage policy
from geopy.geocoders import Nominatim

geolocator = Nominatim(user_agent="lifelog-picam")


def nominatim_reverse(lat: float, lon: float) -> dict | None:
    """Reverse-geocode with cache + rate limiting. Returns {city, region, country}."""
    global _last_request
    key = f"nominatim_{round(lat,2)}_{round(lon,2)}"  # coarse rounding to avoid excessive cache fragmentation
    cached = cache_get(key)
    if cached is not None:
        return cached

    wait = RATE_LIMIT - (time.time() - _last_request)
    if wait > 0:
        time.sleep(wait)

    try:
        location = geolocator.reverse(f"{lat}, {lon}", language="en")
        _last_request = time.time()
        raw = location.raw
        if raw:
            cache_set(key, raw)
        return raw
    except Exception as e:
        print(f"Nominatim error for {lat}, {lon}: {e}")
        return None


def parse_nominatim(data: dict) -> dict:
    addr = data.get("address", {})
    country_code = addr.get("country_code", "").upper()
    city = [
        addr.get("city"), addr.get("town"),
        addr.get("village"),
        addr.get("municipality"),
        addr.get("county")
    ]
    city = [c for c in city if c]
    region = [
        addr.get("state"),
        addr.get("region"),
        addr.get("province"),
        addr.get("state_district"),
    ]
    region = city + [r for r in region if r]
    country = cc_to_country(country_code) or addr.get("country", "")
    result = {"city": city, "region": region, "country": country}
    return result


# ─── Haversine ────────────────────────────────────────────────────────────────


def haversine(lat1, lon1, lat2, lon2):
    R = 6_371_000
    phi1, phi2 = np.radians(lat1), np.radians(lat2)
    a = (
        np.sin(np.radians(lat2 - lat1) / 2) ** 2
        + np.cos(phi1) * np.cos(phi2) * np.sin(np.radians(lon2 - lon1) / 2) ** 2
    )
    return 2 * R * np.arcsin(np.sqrt(a))


# ─── Image lookup ─────────────────────────────────────────────────────


def get_images_for_segment(
    image_gps: pd.DataFrame, segment_id: int
) -> list[str]:
    """
    Return sorted list of image filenames within [start_ts, end_ts] for date.
    col is a pymongo Collection.
    """
    return image_gps[image_gps["segment_id"] == segment_id]["image_path"].tolist()


# ─── CLIP feature loading ─────────────────────────────────────────────────────
def get_stop_features(images: list[str]) -> torch.Tensor | None:
    """
    Given a list of image filenames (bare, no path prefix), look them up in
    all_feats and return a (N, D) float tensor, or None if nothing found.
    Images stored as YYYY-MM-DD/YYYYMMDD_HHMMSS_000.jpg in all_feats.
    """
    vecs = []
    rows = session.execute(
        select(CLIPEmbedding.embedding)
        .join(Image.clip_embedding)
        .where(Image.image_path.in_(images))
    )
    for r in rows:
        vecs.append(r.embedding)
    if not vecs:
        return None
    t = torch.tensor(np.stack(vecs), dtype=torch.float32).to(DEVICE)
    t = t / t.norm(dim=-1, keepdim=True)
    return t


# ─── CLIP scoring ─────────────────────────────────────────────────────────────


def score_places(
    places: list[dict], image_features: torch.Tensor, model, weights: list[float]
) -> tuple[dict, float]:
    """
    Build text labels, encode with CLIP, score against image_features.
    Returns (best_place, probability).
    """
    labels = []
    for p in places:
        name = unidecode(re.sub(r"[\(\[].*?[\)\]]", "", p["name"]))
        cats = ", ".join(p["categories"]) if p["categories"] else "place"
        labels.append(f"I am in a {cats} called {name}")

    text_tokens = clip.tokenize(labels, truncate=True).to(DEVICE)
    with torch.no_grad():
        text_features = model.encode_text(text_tokens).float()
        text_features /= text_features.norm(dim=-1, keepdim=True)

    # Mean similarity across all images in the stop
    mean_sim = (image_features @ text_features.T).mean(dim=0)  # (N_places,)
    w = torch.tensor(weights, dtype=torch.float32).to(DEVICE)
    weighted = w * mean_sim
    probs = (100 * weighted).softmax(dim=0)
    best_idx = probs.argmax().item()
    return places[best_idx], probs[best_idx].item() / weights[best_idx]


# ─── NULL sentinel ────────────────────────────────────────────────────────────

NULL_PLACE = {
    "name": "Unknown Place",
    "fsq_place_id": "",
    "categories": [],
    "parent": "",
    "parent_id": "",
    "prob": 0.0,
    "location": {},
}

# ─── Per-row enrichment ───────────────────────────────────────────────────────

_CC = {
    "IE": "Ireland",
    "GB": "United Kingdom",
    "US": "United States",
    "FR": "France",
    "DE": "Germany",
    "ES": "Spain",
    "IT": "Italy",
    "NL": "Netherlands",
    "BE": "Belgium",
    "PT": "Portugal",
    "PL": "Poland",
    "SE": "Sweden",
    "NO": "Norway",
    "DK": "Denmark",
    "FI": "Finland",
    "CH": "Switzerland",
    "AT": "Austria",
    "CZ": "Czech Republic",
    "HU": "Hungary",
    "RO": "Romania",
    "CN": "China",
    "JP": "Japan",
    "KR": "South Korea",
    "AU": "Australia",
    "CA": "Canada",
    "BR": "Brazil",
    "IN": "India",
    "ZA": "South Africa",
    "MX": "Mexico",
    "AR": "Argentina",
}


def cc_to_country(code: str) -> str:
    return _CC.get((code or "").upper(), (code or "").upper())


def build_location(location: dict) -> dict:
    """
    Build the location subdocument from FSQ response + CSV row.

    Shape:
      {
        name:    str,                          # FSQ place name
        stop:    bool,                         # always True here (we skip moves)
        region:  [region, locality, country],  # coarse → fine administrative
        city:    [middle parts of formatted_address],
        country: str,                          # full country name
      }
    """
    loc = location.get("location", {})

    country_code = loc.get("country", "")
    country_name = cc_to_country(country_code)

    region = [
        x
        for x in [
            loc.get("region", ""),
            loc.get("locality", ""),
            country_name,
        ]
        if x
    ]

    # city: middle tokens of formatted_address, stripping first and last
    formatted = loc.get("formatted_address", "")
    parts = [p.strip() for p in formatted.split(",")]
    city = parts[1:-1] if len(parts) > 2 else parts

    return {
        "region": region,
        "city": city,
        "country": country_name,
        "address": formatted,
    }


def enrich_stop(row: pd.Series, model, image_gps: pd.DataFrame) -> dict:
    """
    Given a segment row, return a dict of enrichment fields.
    Non-stop segments pass straight through with NULL values.
    """
    result = {
        "fsq_place_id": "",
        "name": row["movement"],
        "categories": row["movement"],
        "prob": 0.0,
        "parent": "",
        "parent_id": "",
        "note": "default",
        "city": "",
        "region": [],
        "country": "",
        "address": "",
    }

    if row["is_stop"] != 1:
        return result

    lat, lon, altitude = (
        row["centroid_lat"],
        row["centroid_lon"],
        row.get("centroid_alt", 0.0),
    )
    if pd.isna(lat) or pd.isna(lon):
        result["name"] = {"lat": None, "lon": None, "altitude": None}
        result["note"] = "Missing GPS data"
        return result

    # Home shortcut
    if haversine(lat, lon, HOME_LAT, HOME_LON) < DISTANCE_THRESHOLD:
        result["name"] = "HOME"
        result["city"] = "Dublin"
        result["country"] = "Ireland"
        result["region"] = ["Dublin", "Ireland"]
        result["note"] = "HOME"
        result["address"] = "HOME"
        return result

    if haversine(lat, lon, WORK_LAT, WORK_LON) < DISTANCE_THRESHOLD:
        result["name"] = "WORK"
        result["city"] = "Dublin"
        result["country"] = "Ireland"
        result["region"] = ["Dublin", "Ireland"]
        result["note"] = "WORK"
        result["address"] = "Collins Ave Ext, Whitehall, Dublin 9"
        return result

    # Nearby places from Foursquare
    max_radius = max(DISTANCE_THRESHOLD, int(row.get("max_radius", DISTANCE_THRESHOLD)))
    raw_places = get_nearby_places(lat, lon, altitude)
    if not raw_places:
        if row["movement"] == "Inside":
            result["name"] = "Unknown Place"
        else:
            row["name"] = row["movement"]

        result["note"] = "No nearby places found"
        result.update(parse_nominatim(nominatim_reverse(lat, lon) or {}))
        return result

    places = [parse_place(p) for p in raw_places]
    places = [
        p
        for p in places
        if p["distance"] is None
        or p["distance"] < max(DISTANCE_THRESHOLD * 2, max_radius * 2)
    ]
    places = expand_with_parents(places, DISTANCE_THRESHOLD)

    first_place = places[0] if places else None

    if not places:
        # print(original_places)
        result["name"] = "Unknown Place"
        result["note"] = "No nearby places within distance threshold"
        if first_place:
            result.update(build_location(first_place))
        else:
            result.update(parse_nominatim(nominatim_reverse(lat, lon) or {}))
        return result

    # Images for this segment
    date = str(row["start"])[:10]  # "YYYY-MM-DD" from formatted_time
    images = get_images_for_segment(image_gps, row["segment_id"])
    image_features = get_stop_features(images)
    if image_features is None:
        # Get the most likely place based on distance alone, if we have no images or features
        best = min(
            places,
            key=lambda p: p["distance"] if p["distance"] is not None else float("inf"),
        )
        prob = 0.0
    else:
        weights = [1.0] * len(places)
        best, prob = score_places(places, image_features, model, weights)

    result.update(
        {
            "name": best["name"],
            "fsq_place_id": best["fsq_place_id"],
            "categories": ", ".join(best["categories"]),
            "prob": float(prob),
            "parent": best["parent"],
            "parent_id": best["parent_id"],
            "location": json.dumps(best["location"]),
            **build_location(best),
        }
    )
    return result


# ─── City clustering for move segments ───────────────────────────────────────
from sklearn.cluster import DBSCAN

MOVE_EPS = 5 / 6371.0  # ~5 km in radians
MOVE_MIN_PTS = 3


def cluster_points_by_city(
    points: list[tuple[float, float]],
) -> list[tuple[float, float]]:
    """
    DBSCAN with ~5 km EPS.  Returns one representative (lat, lon) per cluster.
    Falls back to centroid if too few points.
    """
    if len(points) < 2:
        return points or []

    arr = np.radians(np.array(points))
    labels = DBSCAN(
        eps=MOVE_EPS,
        min_samples=MOVE_MIN_PTS,
        algorithm="ball_tree",
        metric="haversine",
    ).fit_predict(arr)

    representatives = []
    for cl in sorted(set(labels)):
        mask = labels == cl
        cluster_pts = np.array(points)[mask]
        # Use the median point as representative
        med = np.median(cluster_pts, axis=0)
        representatives.append((float(med[0]), float(med[1])))

    return representatives


def build_move_location(city_entries: list[dict]) -> dict:
    """
    Location for a move segment.
    city_entries is a list of { city, region, country } dicts, one per cluster.
    Deduped by city name.
    """
    seen = set()
    deduped = []
    cities = []
    regions = []
    for e in city_entries:
        if e["city"] and e["country"]:
            key = e["city"][0].lower() + "_" + e["country"].lower()
        else:
            key = e["country"]
            
        cities.extend(e["city"])
        regions.extend(e["region"])
        if key not in seen:
            seen.add(key)
            deduped.append(e)
    countries = list(dict.fromkeys(e["country"] for e in deduped if e["country"]))

    return {
        "name": " → ".join(e["city"][0] for e in deduped if e["city"]) or "unknown",
        "stop": False,
        "cities": deduped,  # list of {city, region, country}
        "city": list(set(cities)),
        "region": list(set(regions)),
        "country": countries[0] if len(countries) == 1 else countries,
        "_geocoder": "nominatim",
    }


def enrich_move(row: pd.Series, image_gps: pd.DataFrame) -> dict:
    # Pull raw GPS points for this time window
    filtered = image_gps[
        (image_gps["timestamp"] >= row["start_ts"])
        & (image_gps["timestamp"] <= row["end_ts"])
    ]
    gps_pts = list(zip(filtered["latitude"].tolist(), filtered["longitude"].tolist()))

    if not gps_pts:
        # Fall back to centroid
        gps_pts = (
            [(row["centroid_lat"], row["centroid_lon"])]
            if not pd.isna(row["centroid_lat"]) and not pd.isna(row["centroid_lon"])
            else []
        )

    # Cluster into cities
    representatives = cluster_points_by_city(gps_pts)

    city_entries = []
    for lat, lon in representatives:
        geo = parse_nominatim(nominatim_reverse(lat, lon) or {})
        if geo:
            city_entries.append(
                {
                    "city": geo["city"],
                    "region": geo["region"],
                    "country": geo["country"],
                }
            )

    # get the most common movement type for the segment
    if not city_entries:
        return {
            "name": "",
            "categories": row.get("movement", ""),
            "city": "",
            "region": "",
            "country": "",
            "note": "move segment with no GPS data",
        }

    location = build_move_location(city_entries)
    return {
        "name": location["name"],
        "categories": row.get("movement", ""),
        "city": location["city"],
        "region": location["region"],
        "country": location["country"],
        "note": "move segment enriched with Nominatim geocoding",
    }


# ─── Main ─────────────────────────────────────────────────────────────────────


def run(segments_file: str = SEGMENTS_FILE, output_file: str = OUTPUT_FILE):
    print("Loading segments…")
    seg = pd.read_csv(segments_file)
    seg["start_ts"] = pd.to_datetime(seg["start_ts"], format="ISO8601").dt.tz_localize(None)
    seg["end_ts"] = pd.to_datetime(seg["end_ts"], format="ISO8601").dt.tz_localize(None)

    print("Loading image GPS data…")
    image_gps = pd.read_csv(GPS_FILE)
    # set index to timestamp for faster filtering
    image_gps["timestamp"] = pd.to_datetime(image_gps["timestamp"], format="ISO8601")
    # not timezone-aware
    image_gps["timestamp"] = image_gps["timestamp"].dt.tz_localize(None)


    print("Loading CLIP model…")
    model, _ = load_model()

    # Prep output columns
    for col_name in [
        "fsq_place_id",
        "name",
        "categories",
        "prob",
        "parent",
        "parent_id",
        "city",
        "region",
        "country",
        "note",
        "address",
    ]:
        if col_name not in seg.columns:
            seg[col_name] = "" if col_name != "prob" else 0.0

    stop_rows = seg[seg["is_stop"] == 1]
    print(f"\n{len(stop_rows)} stop segments to enrich (of {len(seg)} total)\n")
    tf = TimezoneFinder()

    for idx, row in tqdm(seg.iterrows(), total=len(seg), desc="Enriching stops"):
        try:
            movements = image_gps[image_gps["segment_id"] == row["segment_id"]]["movement"].tolist()

            movement = max(set(movements), key=movements.count) if movements else ""
            row["movement"] = movement

            if row["is_stop"] != 1:
                enrichment = enrich_move(row, image_gps)
            else:
                enrichment = enrich_stop(row, model, image_gps)

            enrichment["timezone"] = (
                tf.timezone_at(lng=row["centroid_lon"], lat=row["centroid_lat"]) or ""
            )
            enrichment["movement"] = movement

            for k, v in enrichment.items():
                seg.at[idx, k] = v

        except KeyboardInterrupt:
            print("Interrupted by user, stopping enrichment.")
            break

    os.makedirs(os.path.dirname(output_file) or ".", exist_ok=True)
    seg.to_csv(output_file, index=False, sep=";")
    print(f"\nSaved → {output_file}")
    session.flush()
    session.close()


if __name__ == "__main__":
    run()

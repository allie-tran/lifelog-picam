import bisect
from collections import Counter
import logging
import uuid
import pandas as pd
import numpy as np
from datetime import timedelta
from sklearn.cluster import DBSCAN
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm.session import Session
from sqlalchemy import bindparam, func, select, update
from database.models import RawGPS, Device, ImageGPS, Image, Location
from location.enrich_stops import enrich_stop, enrich_move
from location.utils import find_timezone

from services.segmentation import load_all_segments

logger = logging.getLogger(__name__)

# ─── Config ───────────────────────────────────────────────────────────────────
GAP_SECONDS = 5 * 60       # 5-minute gap → new track
SPEED_THRESHOLD = 50       # m/s — hard teleport cap (≈180 km/h)
# Round-trip spike removal (catches moderate multipath glitches that stay under
# the speed cap): a point is a spike when its in+out path detours far past the
# straight chord between its neighbours, and it juts out by more than the noise
# floor. Corner-safe — a 90° turn detours only ~0.6×chord, far below the ratio.
SPIKE_OFFSET_M = 60        # metres — ignore pops below the GPS noise floor
SPIKE_RATIO = 2.5          # (in+out − chord) must exceed RATIO×chord to drop

# Stay-point detection (Li et al. 2008) — replaces per-track DBSCAN.
# A stop = a run of consecutive points all within STAY_DIST of the run's anchor,
# lasting at least STAY_TIME seconds. Bounds each stop's diameter to ~2*STAY_DIST,
# so slow walks across a large venue (campus/airport) no longer chain into one
# giant cluster the way DBSCAN's transitive linking did.
STAY_DIST = 50             # metres — max distance from anchor to remain in a stop
STAY_TIME = 120            # seconds — min dwell to count as a stop

# Cross-track merge: glue nearby stop centroids into one place_id (haversine radians)
MERGE_EPS = 0.15 / 6371    # ~150 m

# ─── Step 1: Load all points for a device/date into a single DataFrame ─────────

def load_all_points(session: Session, device: str, date: str) -> pd.DataFrame:
    # date is expected in 'YYYY-MM-DD' format; adjust as needed
    stmt = select(RawGPS).join(Device, Device.id == RawGPS.device_id).where(Device.device_id == device, func.date(RawGPS.timestamp) == date).order_by(RawGPS.timestamp)
    all_points = session.execute(stmt).scalars().all()
    all_points = [p.__dict__ for p in all_points]  # Convert ORM objects to dicts
    if not all_points:
        return pd.DataFrame(columns=["latitude", "longitude", "elevation", "timestamp"])

    df = pd.DataFrame(all_points)
    df.sort_values("timestamp", inplace=True)
    # add date column as "YYYY-MM-DD" string for easier merging later
    df["date"] = df["timestamp"].dt.strftime("%Y-%m-%d")
    df["formatted_time"] = df["timestamp"].dt.strftime("%Y-%m-%d %H:%M:%S")
    df.reset_index(drop=True, inplace=True)
    return df

# ─── Step 2: Re-split into tracks based on time gaps ─────────────────────────

def assign_tracks_by_gap(df: pd.DataFrame, gap_seconds: int = GAP_SECONDS) -> pd.DataFrame:
    """
    Ignore original track/segment labels.  Assign a new integer 'track_id'
    whenever consecutive points are more than gap_seconds apart.
    """
    df = df.copy()
    try:
        dt = df["timestamp"].diff().dt.total_seconds().fillna(0)
    except Exception as e:
        print("Error calculating time differences:", e)
        print("Timestamps:", df["timestamp"])
        raise e
    df["track_id"] = (dt > gap_seconds).cumsum()
    return df


# ─── Step 3: Filter speed outliers ───────────────────────────────────────────

def haversine_distance(lat1, lon1, lat2, lon2, alt1, alt2):
    """Distance in metres between two lat/lon points."""
    R = 6_371_000
    phi1, phi2 = np.radians(lat1), np.radians(lat2)
    dphi = np.radians(lat2 - lat1)
    dlam = np.radians(lon2 - lon1)
    a = np.sin(dphi / 2) ** 2 + np.cos(phi1) * np.cos(phi2) * np.sin(dlam / 2) ** 2
    d = 2 * R * np.arcsin(np.sqrt(a))

    # Apply vertical (altitude) distance
    if alt1 is None or alt2 is None:
        alt1 = alt2 = 0
    dz = alt2 - alt1
    return np.sqrt(d ** 2 + dz ** 2)


def filter_speed_outliers(df: pd.DataFrame, threshold_ms: float = SPEED_THRESHOLD) -> pd.DataFrame:
    """
    Drop GPS outliers per track in two passes:

    1. Teleport pass — walk the track keeping a running 'last good' anchor and
       drop any point implying speed > threshold_ms from it.  Measuring against
       the last *kept* point (not the previous row) stops a dropped outlier from
       poisoning the next good point.  A look-ahead tie-break decides whether a
       jump means the new point is bad or the anchor itself was a leading
       outlier — so a bad first fix can't survive and drag the track with it.
    2. Spike pass — drop any remaining interior point whose in+out detour far
       exceeds the straight chord between its neighbours (catches moderate
       multipath glitches that stay under the speed cap).
    """
    rows = []
    for _, grp in df.groupby("track_id"):
        grp = grp.sort_values("timestamp").reset_index(drop=True)
        n = len(grp)
        if n == 0:
            continue
        if n <= 2:                      # too short to cross-check — keep as-is
            rows.append(grp)
            continue

        lat = grp["latitude"].values
        lon = grp["longitude"].values
        alt = grp["elevation"].fillna(0.0).values
        ts  = grp["timestamp"].values

        def _seconds(a: int, b: int) -> float:
            return (ts[b] - ts[a]) / np.timedelta64(1, "s")

        def _dist(a: int, b: int) -> float:
            return haversine_distance(lat[a], lon[a], lat[b], lon[b], alt[a], alt[b])

        def _speed(a: int, b: int) -> float:
            dt = _seconds(a, b)
            return np.inf if dt <= 0 else _dist(a, b) / dt

        # ── Pass 1: teleport removal with last-good anchor + look-ahead ──
        keep = np.ones(n, dtype=bool)
        last = 0
        for i in range(1, n):
            if _speed(last, i) <= threshold_ms:
                last = i
                continue
            # Jump from anchor. If the next sample agrees with i but not with the
            # anchor, the anchor was the outlier; otherwise i is.
            j = i + 1
            if j < n and _speed(i, j) <= threshold_ms and _speed(last, j) > threshold_ms:
                keep[last] = False
                last = i
            else:
                keep[i] = False

        # ── Pass 2: round-trip spike removal over the survivors ──
        idx = np.flatnonzero(keep).tolist()
        for a, b, c in zip(idx, idx[1:], idx[2:]):
            d_in, d_out, chord = _dist(a, b), _dist(b, c), _dist(a, c)
            detour = d_in + d_out - chord
            if min(d_in, d_out) > SPIKE_OFFSET_M and detour > SPIKE_RATIO * max(chord, SPIKE_OFFSET_M):
                keep[b] = False

        rows.append(grp[keep])

    if not rows:
        return df.iloc[0:0]
    return pd.concat(rows, ignore_index=True)


# ─── Step 4: Stay-point detection + stop/move labelling ───────────────────────

def detect_stay_points(
    grp: pd.DataFrame,
    dist_thresh: float = STAY_DIST,
    time_thresh: float = STAY_TIME,
) -> np.ndarray:
    """
    Li et al. (2008) stay-point detection over a single time-ordered track.

    Returns an int array (one per point): -1 = move, and 0,1,2,… for each
    distinct stay within the track.

    A stay is a maximal run of consecutive points all within ``dist_thresh``
    metres of the run's *anchor* (its first point), spanning at least
    ``time_thresh`` seconds. Measuring every point against the fixed anchor
    bounds a stop's diameter to ~2*dist_thresh — unlike DBSCAN, whose
    transitive linking let a slow walk chain an entire building into one
    cluster.
    """
    n = len(grp)
    cluster = np.full(n, -1, dtype=int)
    lat = grp["latitude"].values
    lon = grp["longitude"].values
    ts = grp["timestamp"].values  # numpy datetime64[ns]

    stay_id = 0
    i = 0
    while i < n:
        # Extend the window while points stay within dist_thresh of anchor i.
        j = i + 1
        while j < n:
            d = haversine_distance(lat[i], lon[i], lat[j], lon[j], 0, 0)
            if d > dist_thresh:
                break
            j += 1

        # Points i..j-1 are all within dist_thresh of the anchor.
        dwell = (ts[j - 1] - ts[i]) / np.timedelta64(1, "s")
        if dwell >= time_thresh:
            cluster[i:j] = stay_id
            stay_id += 1
            i = j               # resume scanning from the first point that left
        else:
            i += 1              # too brief — anchor moves on by one point

    return cluster


def annotate_track(grp: pd.DataFrame) -> pd.DataFrame:
    grp = grp.sort_values("timestamp").copy().reset_index(drop=True)
    grp["elevation"] = grp["elevation"].fillna(0.0)  # Handle missing elevation
    if len(grp) < 2:
        grp["cluster"] = -1
        grp["label"] = 0
        grp["label_smooth"] = 0
        return grp

    grp["cluster"] = detect_stay_points(grp)
    grp["label"] = (grp["cluster"] >= 0).astype(int)
    # Stay-point runs are already contiguous and non-overlapping, so no
    # rolling-mode smoothing is needed (it would only blur stop boundaries).
    grp["label_smooth"] = grp["label"]
    return grp


# ─── Step 5: Assign stop_id + merge stop centroids into place_id ─────────────

def assign_stop_and_place_ids(df: pd.DataFrame) -> pd.DataFrame:
    """
    stop_id  — globally unique label for each (track_id, cluster) stop.
               Format: stop_<track_id>_<cluster>.  Stable and unambiguous.
               Non-stop points get None.

    place_id — result of a second DBSCAN pass that merges nearby stop
               centroids across all tracks.  Stops that fall within
               MERGE_EPS of each other share a place_id.
               Format: place_<N>.  Also None for non-stop points.

    The two IDs are independent — you can use stop_id to inspect individual
    visit clusters and place_id to group them into locations.
    """
    stop_df = df[df["label_smooth"] == 1].copy()

    # --- stop_id: one per (track_id, cluster) pair -------------------------
    # Use a string key so it's human-readable in the output
    centroids = (
        stop_df.groupby(["track_id", "cluster"])
        .agg(lat=("latitude", "mean"), lon=("longitude", "mean"), alt=("elevation", "mean"))
        .reset_index()
    )
    # centroids["stop_id"] = centroids.apply(
    #     lambda r: f"stop_{int(r['track_id'])}_{int(r['cluster'])}", axis=1
    # )
    try:
        centroids["stop_id"] = (
            "stop_"
            + centroids["track_id"].astype(int).astype(str)
            + "_"
            + centroids["cluster"].astype(int).astype(str)
        )
    except ValueError:
        print(centroids["track_id"])
        print(centroids["cluster"])

    df = df.merge(
        centroids[["track_id", "cluster", "stop_id"]],
        on=["track_id", "cluster"],
        how="left",
    )
    # Non-stop points (cluster == -1 or label_smooth == 0) get None
    df.loc[df["label_smooth"] != 1, "stop_id"] = None

    # --- place_id: DBSCAN over stop centroids --------------------------------
    if len(centroids) == 0:
        df["place_id"] = None
        return df

    coords_rad = np.radians(centroids[["lat", "lon"]].values)
    merge_labels = run_dbscan_custom(coords_rad, eps=MERGE_EPS, min_samples=1)

    # min_samples=1 means every point is in a cluster (no noise), so
    # place_{N} is always a merged group of ≥1 stop centroids.
    centroids["place_id"] = [f"place_{l}" for l in merge_labels]

    df = df.merge(
        centroids[["track_id", "cluster", "place_id"]],
        on=["track_id", "cluster"],
        how="left",
    )
    df.loc[df["label_smooth"] != 1, "place_id"] = None

    return df


def run_dbscan_custom(coords_rad, eps, min_samples):
    clustering = DBSCAN(
        eps=eps,
        min_samples=min_samples,
        algorithm="ball_tree",
        metric="haversine",
    )
    return clustering.fit_predict(coords_rad)

def analyze_track_gaps(df: pd.DataFrame, speed_threshold_ms: float = 0.5):
    """
    Identifies the 'black boxes' between tracks and classifies
    them as a 'Gap-Stop' or 'Gap-Move'.
    """
    gaps = []
    track_ids = sorted(df["track_id"].unique())

    for i in range(len(track_ids) - 1):
        curr_id = track_ids[i]
        next_id = track_ids[i+1]

        # Get the boundary points
        last_point = df[df["track_id"] == curr_id].iloc[-1]
        first_point = df[df["track_id"] == next_id].iloc[0]

        # Calculate gap metrics
        dt = (first_point["timestamp"] - last_point["timestamp"]) / np.timedelta64(1, 's')  # gap duration in seconds
        dist = haversine_distance(
            last_point["latitude"], last_point["longitude"],
            first_point["latitude"], first_point["longitude"],
            last_point["elevation"], first_point["elevation"]
        )

        avg_speed = dist / dt if dt > 0 else 0

        # Classification
        # 1 = Stop (Stationary gap), 0 = Move (Transit gap)
        gap_label = 1 if (avg_speed < speed_threshold_ms and dist < 100) else 0  # Consider it a stop if speed is low and distance is short

        # Add 2 token entries to represent the gap in the main DataFrame
        for i, point in enumerate([last_point, first_point]):
            timestamp = point["timestamp"]
            offset = pd.Timedelta(seconds=min(dt/2, 1))  # small offset to place the gap point between the two tracks
            timestamp += offset if i == 0 else -offset
            gaps.append({
                "track_id": f"gap_{curr_id}_{next_id}",
                "formatted_time": point["formatted_time"],
                "latitude": point["latitude"],
                "longitude": point["longitude"],
                "elevation": point["elevation"],
                "timestamp": timestamp,
                "label": gap_label,
                "label_smooth": gap_label,
                "avg_speed": avg_speed,
                "stop_id": f"gap_stop_{curr_id}_{next_id}" if gap_label == 1 else None,
                "place_id": f"gap_place_{curr_id}_{next_id}" if gap_label == 1 else None,
                "date": point["date"],
                "interpolated": True,
            })
    return pd.DataFrame(gaps)

# ─── Step 6: Build segment list ──────────────────────────────────────────────

def build_segments(df: pd.DataFrame) -> tuple[pd.DataFrame, list[dict]]:
    """
    Collapse consecutive same-label rows (within each track) into segments.
    Returns a list of dicts with keys:
        track_id, start, end, label, centroid_lat, centroid_lon, place_id
    """
    segments = []

    for track_id, grp in df.groupby("track_id"):
        grp = grp.sort_values("timestamp").reset_index(drop=True)
        seg_start = 0

        for i in range(1, len(grp) + 1):
            boundary = (
                i == len(grp)
                or grp.loc[i, "label_smooth"] != grp.loc[seg_start, "label_smooth"]
            )
            # Within a stop run, also break when place_id changes so two
            # back-to-back stays (no move point between them) don't collapse
            # into one segment with a blended centroid. Only checked for stops,
            # where place_id is always a valid string — avoids NaN!=NaN on moves.
            if not boundary and grp.loc[seg_start, "label_smooth"] == 1:
                boundary = grp.loc[i, "place_id"] != grp.loc[seg_start, "place_id"]
            if boundary:
                seg = grp.iloc[seg_start:i]
                entry = {
                    "track_id":     track_id,
                    "start":        seg["formatted_time"].iloc[0],
                    "end":          seg["formatted_time"].iloc[-1],
                    "start_ts":     seg["timestamp"].iloc[0],
                    "end_ts":       seg["timestamp"].iloc[-1],
                    "is_stop":      seg["label_smooth"].iloc[0],
                    "centroid_lat": seg["latitude"].mean(),
                    "centroid_lon": seg["longitude"].mean(),
                    "centroid_alt": seg["elevation"].mean(),
                    "start_lat":    seg["latitude"].iloc[0],
                    "start_lon":    seg["longitude"].iloc[0],
                    "start_alt":    seg["elevation"].iloc[0],
                    "end_lat":      seg["latitude"].iloc[-1],
                    "end_lon":      seg["longitude"].iloc[-1],
                    "end_alt":      seg["elevation"].iloc[-1],
                    "n_points":     len(seg),
                    "place_id":     seg["place_id"].iloc[0] if "place_id" in seg else None,
                    "interpolated": seg["interpolated"].mode()[0] if "interpolated" in seg else None,
                }
                segments.append(entry)
                seg_start = i

    # Sort segments by start time for easier analysis
    segments.sort(key=lambda x: x["start_ts"])
    df.sort_values("timestamp", inplace=True)
    return df, segments


# ─── Step 7: Assign GPS points to images based on timestamp proximity ────────────────
def assign_gps_to_images(session, date, device, points, point_timestamps):
    # Assign GPS data to images
    images = session.execute(
        select(Image.id, Image.image_path, Image.timestamp).where(
            Image.device == device,
            Image.date == date
        )
    )
    images = list(images)
    if len(images) == 0:
        return []  # No images for this date, skip processing

    stats = Counter()
    gaps = []  # track actual time deltas for distribution insight
    rows = []

    for image in images:
        img_ts = image.timestamp.replace(
            tzinfo=None
        )  # ensure naive datetime for comparison

        # Find insertion point
        j = bisect.bisect_left(point_timestamps, img_ts)

        # Get candidates either side
        candidates = []
        if j < len(points):
            candidates.append(points[j])
        if j > 0:
            candidates.append(points[j - 1])

        if not candidates:
            stats["no_gps_data"] += 1
            continue  # No GPS data at all

        closest = min(candidates, key=lambda p: abs(p["timestamp"] - img_ts))
        closest = closest.copy()  # avoid mutating original point
        gap_s = abs(closest["timestamp"] - img_ts)
        gaps.append(gap_s)

        if gap_s <= timedelta(seconds=30):
            stats["within_30s"] += 1
        elif gap_s <= timedelta(seconds=60):
            stats["within_60s"] += 1
        else:
            stats["gap_too_large"] += 1
            # interpolation could be done here
            left = points[j - 1] if j > 0 else None
            right = points[j] if j < len(points) else None
            closest = left.copy() if left else right.copy() if right else None
            assert closest is not None, "Logic error: at least one candidate should exist"
            if left and right:
                total_gap = (right["timestamp"] - left["timestamp"]).total_seconds()
                if total_gap > 0:
                    img_gap = (img_ts - left["timestamp"]).total_seconds()
                    ratio = img_gap / total_gap
                    closest.update(
                        {
                            "latitude": left["latitude"]
                            + ratio * (right["latitude"] - left["latitude"]),
                            "longitude": left["longitude"]
                            + ratio * (right["longitude"] - left["longitude"]),
                            "elevation": left["elevation"]
                            + ratio * (right["elevation"] - left["elevation"]),
                            "timestamp": img_ts,
                            "date": date,
                            "interpolated": True,
                            "track_id": left["track_id"],  # assign to left track by default
                        }
                    )
                else:
                    closest.update(
                        {
                            "latitude": left["latitude"],
                            "longitude": left["longitude"],
                            "elevation": left["elevation"],
                            "timestamp": img_ts,
                            "interpolated": True,
                            "track_id": left["track_id"],  # assign to left track by default
                        }
                    )
            elif left:
                closest.update(
                    {
                        "latitude": left["latitude"],
                        "longitude": left["longitude"],
                        "elevation": left["elevation"],
                        "timestamp": img_ts,
                        "interpolated": True,
                        "track_id": left["track_id"],  # assign to left track by default
                    }
                )
            elif right:
                closest.update(
                    {
                        "latitude": right["latitude"],
                        "longitude": right["longitude"],
                        "elevation": right["elevation"],
                        "timestamp": img_ts,
                        "interpolated": True,
                        "track_id": right["track_id"],  # assign to right track by default
                    }
                )
            else:
                print(
                    f"Warning: No GPS data to interpolate for image {image.image_path} at {img_ts}"
                )

        closest["image_id"] = image.id
        closest["image_path"] = image.image_path
        closest["gaps_s"] = gap_s.total_seconds()
        closest["date"] = date
        rows.append(closest)

    return rows

# ─── Step 8: Geocode segments → Location table ───────────────────────────────

def enrich_and_index_segments(
    session: Session,
    segments: list[dict],
    df: pd.DataFrame,
    device: str,
) -> None:
    """
    For every segment:
      - Stop  → enrich_stop(centroid) via Nominatim zoom=18 + Wikidata
      - Move  → enrich_move(gps_pts) builds "City A → City B" from track points

    Upserts a Location row (keyed on OSM element id or rounded coords) and
    bulk-updates Image.location_id for all images in the segment's time window.
    """
    # Pass 1: enrich all stop segments up front so move segments can reference
    # their neighbours' names when building "StopBefore → StopAfter" labels.
    stop_geos: dict[int, dict] = {}
    for i, seg in enumerate(segments):
        lat = seg.get("centroid_lat")
        lon = seg.get("centroid_lon")
        if lat is None or lon is None or pd.isna(lat) or pd.isna(lon):
            continue
        if bool(seg.get("is_stop")):
            stop_geos[i] = enrich_stop(float(lat), float(lon))

    for i, seg in enumerate(segments):
        lat = seg.get("centroid_lat")
        lon = seg.get("centroid_lon")
        if lat is None or lon is None or pd.isna(lat) or pd.isna(lon):
            continue

        is_stop = bool(seg.get("is_stop"))
        start_ts = seg.get("start_ts")
        end_ts = seg.get("end_ts")

        if is_stop:
            geo = stop_geos.get(i) or enrich_stop(float(lat), float(lon))
        else:
            seg_df = (
                df[(df["timestamp"] >= start_ts) & (df["timestamp"] <= end_ts)]
                if start_ts is not None and end_ts is not None
                else pd.DataFrame()
            )
            gps_pts = (
                list(zip(seg_df["latitude"].tolist(), seg_df["longitude"].tolist()))
                if not seg_df.empty else []
            )
            geo = enrich_move(gps_pts, fallback_lat=float(lat), fallback_lon=float(lon))

            # Override move name with adjacent stop names when available.
            prev_stop = next((stop_geos[j] for j in range(i - 1, -1, -1) if j in stop_geos), None)
            next_stop = next((stop_geos[j] for j in range(i + 1, len(segments)) if j in stop_geos), None)
            from_name = prev_stop.get("name") if prev_stop else None
            to_name = next_stop.get("name") if next_stop else None
            if from_name and to_name:
                geo = {**geo, "name": f"{from_name} → {to_name}"}
            elif from_name:
                geo = {**geo, "name": f"From {from_name}"}
            elif to_name:
                geo = {**geo, "name": f"To {to_name}"}

        # Dedup key — in priority: OSM element id → Wikidata QID → 5-decimal coords
        # 5 decimal places ≈ 1 m precision, preventing false merges of nearby places
        if geo.get("osm_id"):
            raw_key = f"osm_{geo['osm_type']}{geo['osm_id']}"
        elif geo.get("wikidata_id"):
            raw_key = f"wikidata_{geo['wikidata_id']}"
        else:
            raw_key = f"nominatim_{lat:.5f}_{lon:.5f}"
        key = f"stop={is_stop},{raw_key}"

        tz = find_timezone(float(lon), float(lat))

        # ── Map geo dict → Location columns ──────────────────────────────────
        name = geo.get("name") or geo.get("suburb") or geo.get("city") or "Unknown"
        cats = geo.get("categories", [])
        categories_str = "; ".join(cats[:5]) if cats else ""
        address = geo.get("address", "") or name

        stmt = insert(Location).values(
            id=uuid.uuid4(),
            key=key,
            name=name,
            stop=is_stop,
            # admin hierarchy
            suburb=geo.get("suburb") or None,
            city=geo.get("city") or None,
            region=geo.get("region") or None,
            country=geo.get("country", ""),
            postcode=geo.get("postcode") or None,
            # geocoder output
            address=address,
            timezone=tz,
            latitude=float(lat),
            longitude=float(lon),
            # OSM provenance
            osm_type=geo.get("osm_type") or None,
            osm_id=geo.get("osm_id") or None,
            # Wikidata
            wikidata_id=geo.get("wikidata_id") or None,
            description=geo.get("description") or None,
            categories=categories_str or None,
        )
        stmt = stmt.on_conflict_do_update(
            index_elements=["key"],
            set_={
                "name": stmt.excluded.name,
                "suburb": stmt.excluded.suburb,
                "city": stmt.excluded.city,
                "region": stmt.excluded.region,
                "country": stmt.excluded.country,
                "postcode": stmt.excluded.postcode,
                "address": stmt.excluded.address,
                "timezone": stmt.excluded.timezone,
                "latitude": stmt.excluded.latitude,
                "longitude": stmt.excluded.longitude,
                "osm_type": stmt.excluded.osm_type,
                "osm_id": stmt.excluded.osm_id,
                "wikidata_id": stmt.excluded.wikidata_id,
                "description": stmt.excluded.description,
                "categories": stmt.excluded.categories,
            },
        ).returning(Location.id)

        location_id = session.execute(stmt).scalar()
        session.flush()

        if location_id and start_ts is not None and end_ts is not None:
            start_dt = start_ts.to_pydatetime() if hasattr(start_ts, "to_pydatetime") else start_ts
            end_dt = end_ts.to_pydatetime() if hasattr(end_ts, "to_pydatetime") else end_ts
            session.execute(
                update(Image)
                .where(Image.device == device)
                .where(Image.timestamp.between(start_dt - timedelta(seconds=5),
                                               end_dt + timedelta(seconds=15))) # Add small buffer to capture images just outside segment bounds
                .values(location_id=location_id)
            )

        logger.info(f"Upserted location {name} (stop={is_stop}) with key={key} and assigned to images between {start_ts} and {end_ts}")

    session.commit()

# ─── Main ─────────────────────────────────────────────────────────────────────

def run_pipeline(session: Session, device: str, date: str):
    logger.info(f"Processing device={device} date={date}")
    df = load_all_points(session, device, date)
    if len(df) == 0:
        logger.warning(f"No GPS data found for device={device} date={date}, skipping.")
        return

    # 2. Re-splitting tracks by time gap…
    df = assign_tracks_by_gap(df)

    # 3. Filter out GPS points with extreme speeds (e.g. >200 km/h) which can break DBSCAN and skew stop centroids.
    df = filter_speed_outliers(df)

    # 4. Running DBSCAN + stop/move labelling per track…
    df = pd.concat(
        [annotate_track(grp) for _, grp in df.groupby("track_id")],
        ignore_index=True,
    )

    # 5. Assigning stop_id and place_id, so we can group by them when building segments.
    df = assign_stop_and_place_ids(df)
    df["interpolated"] = df.get("interpolated", False)  # Ensure the column exists

    # Fill in gaps between tracks with interpolated points, so we can build segments that span the whole day and not just individual tracks.
    gap_df = analyze_track_gaps(df)
    df = pd.concat([df, gap_df], ignore_index=True)
    df = df.sort_values("timestamp").reset_index(drop=True)

    # 6. Building segments by grouping consecutive points with the same stop_id or place_id, and calculating centroids for stop segments.
    df, segments = build_segments(df)

    # 7. Assigning GPS points to images by finding the nearest GPS point (or interpolated point in a gap) for each image timestamp, and calculating the corresponding timezone.
    all_points = df.to_dict(orient="records")
    point_timestamps = df["timestamp"].tolist()
    image_data = []
    session.rollback()

    # Insert assigned GPS data for images in batches
    data = assign_gps_to_images(session, date, device, all_points, point_timestamps)

    rows = []
    for d in data:
        if str(d["timezone"]) in ("None", "nan", ""):
            d["timezone"] = find_timezone(d["latitude"], d["longitude"])

        rows.append(
            {
                "image_id": d["image_id"],
                "latitude": d["latitude"],
                "longitude": d["longitude"],
                "elevation": d["elevation"],
                "timestamp": d["timestamp"].replace(tzinfo=None).timestamp(),
                "timezone": d["timezone"],
                "formatted_time": d["formatted_time"],
                "source": "interpolated" if d.get("interpolated") else "nearest",
                "gap_s": d.get("gaps_s", None),
            }
        )

        if len(rows) >= 100:
            stmt = insert(ImageGPS).values(rows)
            stmt = stmt.on_conflict_do_update(constraint="image_gps_image_id_key", set_={"latitude": stmt.excluded.latitude, "longitude": stmt.excluded.longitude, "elevation": stmt.excluded.elevation, "timestamp": stmt.excluded.timestamp, "timezone": stmt.excluded.timezone, "formatted_time": stmt.excluded.formatted_time, "source": stmt.excluded.source, "gap_s": stmt.excluded.gap_s})
            session.execute(stmt)
            rows = []

    if rows:
        stmt = insert(ImageGPS).values(rows)
        stmt = stmt.on_conflict_do_update(constraint="image_gps_image_id_key", set_={"latitude": stmt.excluded.latitude, "longitude": stmt.excluded.longitude, "elevation": stmt.excluded.elevation, "timestamp": stmt.excluded.timestamp, "timezone": stmt.excluded.timezone, "formatted_time": stmt.excluded.formatted_time, "source": stmt.excluded.source, "gap_s": stmt.excluded.gap_s})
        session.execute(stmt)

    # Update timezone to image
    rows = []
    for d in data:
        if str(d["timezone"]) in ("None", "nan", ""):
            tz = find_timezone(d["latitude"], d["longitude"])
            rows.append({"id": d["image_id"], "timezone": tz})

        if len(rows) >= 100:
            stmt = update(Image).where(Image.id == bindparam("id")).values(timezone=bindparam("timezone"))
            session.execute(stmt, rows)
            rows = []

    if rows:
        stmt = update(Image).where(Image.id == bindparam("id")).values(timezone=bindparam("timezone"))
        session.execute(stmt, rows)

    image_data.extend(data)
    session.commit()

    # 8. Enriching segments with place info and indexing them for search.
    enrich_and_index_segments(session, segments, df, device)
    session.commit()
    # session.execute(
    #     update(Image)
    #     .where(Image.date == date)
    #     .where(Image.device == device)
    #     .values(
    #         segment_id=None,
    #     )
    # )
    # session.commit()
    # print(f"Reset segments for date {date} and device {device}.")
    load_all_segments(session, device, date, skip_annotations=False)
    logger.info(f"Finished processing device={device} date={date}")
    session.flush()

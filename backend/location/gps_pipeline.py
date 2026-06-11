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
from tqdm.auto import tqdm
from database.models import RawGPS, Device, ImageGPS, Image, Location
from location.enrich_stops import enrich_stop, enrich_move
from location.utils import find_timezone

from scripts.segmentation import load_all_segments

logger = logging.getLogger(__name__)

# ─── Config ───────────────────────────────────────────────────────────────────
# DBSCAN params (haversine expects radians)
EPS = 0.05 / 6371          # ~50 metres
MIN_PTS = 3

GAP_SECONDS = 5 * 60       # 5-minute gap → new track
SPEED_THRESHOLD = 50       # m/s outlier cutoff
STOP_RUN_LENGTH = 5        # consecutive same-cluster points to call "stop"
SMOOTH_WINDOW = 5          # rolling-mode window for stop/move label

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
    Compute speed between consecutive points (per track) and drop points
    that imply speed > threshold_ms metres/second.
    """
    rows = []
    for _, grp in df.groupby("track_id"):
        grp = grp.sort_values("timestamp").copy()
        grp = grp.reset_index(drop=True)

        lat = grp["latitude"].values
        lon = grp["longitude"].values
        alt = grp["elevation"].values
        ts  = grp["timestamp"].values

        keep = [True]  # always keep the first point
        for i in range(1, len(grp)):
            dt = ts[i] - ts[i - 1]
            if dt <= 0:
                keep.append(False)
                continue
            if alt[i] is None or alt[i - 1] is None:
                dist = haversine_distance(lat[i - 1], lon[i - 1], lat[i], lon[i], 0, 0)
            else:
                dist = haversine_distance(lat[i - 1], lon[i - 1], lat[i], lon[i], alt[i - 1], alt[i])
            speed = dist / (dt / np.timedelta64(1, 's'))
            keep.append(speed <= threshold_ms)

        rows.append(grp[keep])

    result = pd.concat(rows, ignore_index=True)
    return result


# ─── Step 4: DBSCAN clustering + stop/move labelling ─────────────────────────

def run_dbscan(coords_rad: np.ndarray) -> np.ndarray:
    clustering = DBSCAN(
        eps=EPS,
        min_samples=MIN_PTS,
        algorithm="ball_tree",
        metric="haversine",
    )
    return clustering.fit_predict(coords_rad)


def label_stop_move(cluster_labels: np.ndarray, run_length: int = STOP_RUN_LENGTH) -> np.ndarray:
    """
    If at least run_length consecutive points share the same non-noise cluster,
    mark them 'stop'; everything else is 'move'.
    """
    n = len(cluster_labels)
    labels = np.array([0] * n, dtype=object)

    i = 0
    while i < n:
        cl = cluster_labels[i]
        if cl == -1:           # noise → always move
            i += 1
            continue
        j = i
        while j < n and cluster_labels[j] == cl:
            j += 1
        run = j - i
        if run >= run_length:
            labels[i:j] = 1
        i = j

    return labels


def smooth_labels(labels: np.ndarray, window: int = SMOOTH_WINDOW) -> np.ndarray:
    """Rolling majority-vote smoothing."""
    s = pd.Series(labels)
    def majority(x):
        return x.mode()[0]
    smoothed = s.rolling(window, center=True, min_periods=1).apply(
        lambda x: 1 if (x.sum() > len(x) / 2) else 0
    )
    return smoothed.astype(int).values


def annotate_track(grp: pd.DataFrame) -> pd.DataFrame:
    grp = grp.sort_values("timestamp").copy().reset_index(drop=True)
    if len(grp) < MIN_PTS:
        grp["cluster"] = -1
        grp["label"] = 0
        grp["label_smooth"] = 0
        return grp

    coords_rad = np.radians(grp[["latitude", "longitude"]].values)
    grp["elevation"] = grp["elevation"].fillna(0.0)  # Handle missing elevation
    grp["cluster"] = run_dbscan(coords_rad)
    grp["label"] = label_stop_move(grp["cluster"].values)
    grp["label_smooth"] = smooth_labels(grp["label"].values)
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

    MERGE_EPS = 0.1 / 6371   # ~100 m merge radius — adjust to taste
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
            if i == len(grp) or grp.loc[i, "label_smooth"] != grp.loc[seg_start, "label_smooth"]:
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
                    "interpolated": seg["interpolated"].mode()[0] if "interpolated" in seg else None,
                }
                segments.append(entry)
                seg_start = i

    # Sort segments by start time for easier analysis
    segments.sort(key=lambda x: x["start_ts"])

    print("   Re-assigning segment IDs to order...")

    # Assign segment_ids
    for i, seg in enumerate(segments):
        seg["segment_id"] = i
        df.loc[(df["track_id"] == seg["track_id"]) &
               (df["timestamp"] >= seg["start_ts"]) &
               (df["timestamp"] <= seg["end_ts"]), "segment_id"] = seg["segment_id"]

    df["segment_id"] = df["segment_id"].astype(int)
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
    for seg in tqdm(segments, desc="   Geocoding"):
        lat = seg.get("centroid_lat")
        lon = seg.get("centroid_lon")
        if lat is None or lon is None or pd.isna(lat) or pd.isna(lon):
            continue

        is_stop = bool(seg.get("is_stop"))
        start_ts = seg.get("start_ts")
        end_ts = seg.get("end_ts")

        if is_stop:
            geo = enrich_stop(float(lat), float(lon))
        else:
            seg_df = df[
                (df["timestamp"] >= start_ts) & (df["timestamp"] <= end_ts)
            ] if start_ts is not None and end_ts is not None else pd.DataFrame()
            gps_pts = (
                list(zip(seg_df["latitude"].tolist(), seg_df["longitude"].tolist()))
                if not seg_df.empty else []
            )
            geo = enrich_move(gps_pts, fallback_lat=float(lat), fallback_lon=float(lon))

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
                .where(Image.timestamp.between(start_dt, end_dt))
                .values(location_id=location_id)
            )
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
    #         activity="",
    #         activity_description="",
    #         activity_confidence="",
    #         segment_id=None,
    #     )
    # )
    # session.commit()
    # print(f"Reset segments for date {date} and device {device}.")
    load_all_segments(session, device, date, skip_annotations=False)
    logger.info(f"Finished processing device={device} date={date}")
    session.flush()

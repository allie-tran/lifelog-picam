import os
import gpxpy
import pandas as pd
import numpy as np
from datetime import timezone
from sklearn.cluster import DBSCAN
from torch import ne

# ─── Config ───────────────────────────────────────────────────────────────────

FOLDER = "GPS"

# DBSCAN params (haversine expects radians)
EPS = 0.05 / 6371          # ~50 metres
MIN_PTS = 3

GAP_SECONDS = 5 * 60       # 5-minute gap → new track
SPEED_THRESHOLD = 50       # m/s outlier cutoff
STOP_RUN_LENGTH = 5        # consecutive same-cluster points to call "stop"
SMOOTH_WINDOW = 5          # rolling-mode window for stop/move label

# ─── GPX field names (adjust to your GPX_10_POINT_FIELDS) ────────────────────

GPX_FIELD_NAMES = ["latitude", "longitude", "elevation"]

# ─── Step 1: Parse all GPX files → flat list of points ───────────────────────

def parse_gpx_file(gps_file, key=None):
    """Return a flat list of point dicts from a single GPX file."""
    try:
        with open(gps_file, "r") as f:
            gpx = gpxpy.parse(f)
    except Exception as e:
        print(f"Error parsing {gps_file}: {e}")
        return []

    points = []
    for t, track in enumerate(gpx.tracks):
        for s, segment in enumerate(track.segments):
            for point in segment.points:
                if point.time is None:
                    continue
                entry = {name: getattr(point, name, None) for name in GPX_FIELD_NAMES}
                point.time = point.time.replace(tzinfo=timezone.utc)
                entry["timestamp"] = point.time
                entry["formatted_time"] = point.time.strftime("%Y%m%d_%H%M%S")
                entry["source_track"] = t
                entry["source_segment"] = s
                entry["source_file"] = key or gps_file
                points.append(entry)
    return points


def load_all_points(folder: str) -> pd.DataFrame:
    all_points = []
    for f in sorted(os.listdir(folder)):
        if not f.endswith(".gpx"):
            continue
        # if not f.startswith("20220203"):  # quick filter for my files — adjust/remove as needed
        #     continue
        gps_file = os.path.join(folder, f)
        pts = parse_gpx_file(gps_file, key=f)
        if pts:
            all_points.extend(pts)

        # if len(all_points) > 10000:
        #     break  # safety cutoff for testing — remove for full processing

    df = pd.DataFrame(all_points)
    df.sort_values("timestamp", inplace=True)
    df.reset_index(drop=True, inplace=True)
    return df


# ─── Step 2: Re-split into tracks based on time gaps ─────────────────────────

def assign_tracks_by_gap(df: pd.DataFrame, gap_seconds: int = GAP_SECONDS) -> pd.DataFrame:
    """
    Ignore original track/segment labels.  Assign a new integer 'track_id'
    whenever consecutive points are more than gap_seconds apart.
    """
    df = df.copy()
    dt = df["timestamp"].diff().dt.total_seconds().fillna(0)
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
    centroids["stop_id"] = centroids.apply(
        lambda r: f"stop_{int(r['track_id'])}_{int(r['cluster'])}", axis=1
    )

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
                "interpolated": True,
            })
    return pd.DataFrame(gaps)

# ─── Step 6: Build segment list ──────────────────────────────────────────────

def build_segments(df: pd.DataFrame) -> list[dict]:
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


# ─── Main ─────────────────────────────────────────────────────────────────────

def run_pipeline(folder: str = FOLDER) -> tuple[pd.DataFrame, list[dict]]:
    print("1. Loading GPX files…")
    df = load_all_points(folder)
    print(f"   {len(df)} raw points loaded")

    print("2. Re-splitting tracks by time gap…")
    df = assign_tracks_by_gap(df)
    print(f"   {df['track_id'].nunique()} tracks after re-splitting")

    print("3. Filtering speed outliers…")
    before = len(df)
    df = filter_speed_outliers(df)
    print(f"   Removed {before - len(df)} outlier points")

    print("4. Running DBSCAN + stop/move labelling per track…")
    df = pd.concat(
        [annotate_track(grp) for _, grp in df.groupby("track_id")],
        ignore_index=True,
    )

    print("5. Merging stop centroids…")
    df = assign_stop_and_place_ids(df)
    df["interpolated"] = df.get("interpolated", False)  # Ensure the column exists

    print("   Filling gaps between tracks…")
    gap_df = analyze_track_gaps(df)
    df = pd.concat([df, gap_df], ignore_index=True)
    df = df.sort_values("timestamp").reset_index(drop=True)

    print("6. Building segment list…")
    df, segments = build_segments(df)
    print(f"   {len(segments)} segments total")

    seg_df = pd.DataFrame(segments)
    return df, seg_df


if __name__ == "__main__":
    df, seg_df = run_pipeline()
    seg_df.sort_values("start", inplace=True)

    os.makedirs("files", exist_ok=True)
    print("\n─── Annotated points sample ───")
    print(df[["segment_id", "track_id", "formatted_time", "latitude", "longitude", "elevation", "label_smooth", "interpolated"]].head(5).to_string(index=False))
    df.to_csv("files/annotated_points.csv", index=False)
    print("\nSaved → annotated_points.csv")

    print("\n─── Segment summary ───")
    print(seg_df[["segment_id", "track_id", "start", "end", "is_stop", "centroid_lat", "centroid_lon", "centroid_alt"]].head(5).to_string(index=False))
    seg_df.to_csv("files/segments.csv", index=False)
    print("\nSaved → segments.csv")

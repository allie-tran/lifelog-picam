import bisect
from collections import Counter, defaultdict
import logging
import uuid
import pandas as pd
import numpy as np
from datetime import timedelta, timezone
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError
from sklearn.cluster import DBSCAN
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm.session import Session
from sqlalchemy import case, delete, func, or_, select, update
from database.models import RawGPS, Device, ImageGPS, Image, Location, GpsStopSegment
from location.enrich_stops import enrich_stop, enrich_move
from location import poi_gazetteer as pgaz
from location.utils import find_timezone
from location import transport_mode as tmode

from services.segmentation import load_all_segments
from integrations.sessions.redis import redis_client

logger = logging.getLogger(__name__)

# ─── Config ───────────────────────────────────────────────────────────────────
GAP_SECONDS = 5 * 60       # 5-minute gap → new track
SPEED_THRESHOLD = 50       # m/s — hard teleport cap (≈180 km/h)
# Quality gate — drop fixes whose reported horizontal accuracy radius is worse
# than this before any track/stay processing, so junk never reaches stay
# detection or the speed/spike filters. Only applied to fixes that *report* an
# accuracy (Android fused); legacy rows with NULL accuracy are always kept.
ACCURACY_MAX_M = 50        # metres — reject fixes looser than this
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
STAY_TIME = 60 * 5         # seconds — min dwell to count as a stop

# Brief-excursion tolerance for stay detection. GPS drift/spikes can throw a few
# fixes beyond STAY_DIST even while the wearer never leaves the place, which
# otherwise splits one stop into stop→walk→stop. A run of out-of-radius points is
# absorbed into the stay (treated as drift) as long as the track returns within
# STAY_DIST of the *same anchor* within EXCURSION_GRACE seconds. Because the
# reference stays the fixed anchor, a genuine walk away never returns in time and
# the stop still closes — the bounded ~2*STAY_DIST diameter is preserved (no
# DBSCAN-style chaining).
EXCURSION_GRACE = STAY_TIME / 2 # seconds — max brief departure that still counts as a stop

# Transport-mode speed sampling — minimum time baseline for a speed sample.
# Point-to-point speed at walk pace is dominated by GPS jitter (±5–10 m per fix
# over ~14 m real steps), which inflates the p85 and pushes walks into the cycle
# band. Measuring chord speed over a ≥45 s window (~60 m walked vs ~10 m jitter)
# restores the signal while p85 still recovers the fast windows of real vehicles.
MIN_SPEED_DT = 45.0        # seconds — min baseline per speed sample

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

# ─── Step 1b: Quality gate — drop low-accuracy fixes ─────────────────────────

def filter_low_accuracy(df: pd.DataFrame, max_accuracy_m: float = ACCURACY_MAX_M) -> pd.DataFrame:
    """Drop fixes whose reported horizontal accuracy radius exceeds
    ``max_accuracy_m``. Null-safe: rows with a missing/NaN accuracy (legacy data,
    non-Android sources) are kept — we only cull a fix that *reports* it is loose.
    No-op when the column is absent entirely.
    """
    if "accuracy" not in df.columns:
        return df
    acc = df["accuracy"].astype("float64").to_numpy()
    # Keep NaN (unknown accuracy) and anything within the radius.
    keep = np.isnan(acc) | (acc <= max_accuracy_m)
    dropped = int((~keep).sum())
    if dropped:
        logger.info("Quality gate: dropped %d/%d fixes with accuracy > %.0f m",
                    dropped, len(df), max_accuracy_m)
    return df.loc[keep].reset_index(drop=True)


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
        logger.error("Error calculating time differences: %s", e)
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
    excursion_grace: float = EXCURSION_GRACE,
) -> np.ndarray:
    """
    Li et al. (2008) stay-point detection over a single time-ordered track,
    hardened against GPS drift.

    Returns an int array (one per point): -1 = move, and 0,1,2,… for each
    distinct stay within the track.

    A stay is a maximal run of points around a fixed *anchor* (its first point):
    every point within ``dist_thresh`` metres of the anchor extends it. A short
    burst of points beyond ``dist_thresh`` is *absorbed* (treated as drift) as
    long as the track returns within ``dist_thresh`` of the anchor within
    ``excursion_grace`` seconds; otherwise the stay ends at the last in-radius
    point. The stay counts as a stop when its total span ≥ ``time_thresh``.

    Measuring against the fixed anchor bounds a stop's diameter to ~2*dist_thresh
    (no DBSCAN-style chaining), while the grace window keeps a single stay from
    being split into stop→walk→stop by transient jitter.
    """
    n = len(grp)
    cluster = np.full(n, -1, dtype=int)
    lat = grp["latitude"].values
    lon = grp["longitude"].values
    ts = grp["timestamp"].values  # numpy datetime64[ns]

    def _secs(a, b):
        return (ts[b] - ts[a]) / np.timedelta64(1, "s")

    stay_id = 0
    i = 0
    while i < n:
        last_in = i             # last point confirmed within dist_thresh of anchor i
        j = i + 1
        while j < n:
            d = haversine_distance(lat[i], lon[i], lat[j], lon[j], 0, 0)
            if d <= dist_thresh:
                last_in = j
                j += 1
                continue
            # Out of radius: peek ahead — does the track return to the anchor
            # within the grace window? If so, absorb the excursion as drift.
            k = j
            returned = False
            while k < n and _secs(j, k) <= excursion_grace:
                if haversine_distance(lat[i], lon[i], lat[k], lon[k], 0, 0) <= dist_thresh:
                    returned = True
                    break
                k += 1
            if returned:
                last_in = k     # points j..k are drift belonging to this stay
                j = k + 1
            else:
                break           # genuine departure — stay ends at last_in

        # Stay spans anchor i .. last_in inclusive.
        dwell = _secs(i, last_in)
        if dwell >= time_thresh:
            cluster[i:last_in + 1] = stay_id
            stay_id += 1
            i = last_in + 1     # resume after the stay (drift points consumed)
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
        logging.warning(
            "ValueError encountered while creating stop_id. "
            "Ensure that track_id and cluster columns contain valid numeric values."
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
def remove_outliers(values: np.ndarray):
    """
    Remove outliers from a 1D array using the IQR method.
    Returns a boolean mask where True indicates non-outlier values.
    """
    q1 = np.percentile(values, 25)
    q3 = np.percentile(values, 75)
    iqr = q3 - q1
    lower_bound = q1 - 1.5 * iqr
    upper_bound = q3 + 1.5 * iqr
    return (values >= lower_bound) & (values <= upper_bound)

def _accuracy_weights(accuracy) -> np.ndarray | None:
    """Per-point centroid weights from the horizontal accuracy radius
    (1/accuracy² — inverse variance, so a tight ±5 m fix pulls the centroid ~100×
    harder than a loose ±50 m one). Returns None when no point has a usable
    accuracy (all NaN/≤0) so the caller falls back to a plain mean. Points missing
    an accuracy still count, but only as much as the worst *measured* fix, so a
    null-accuracy reading can never dominate a well-measured one.
    """
    if accuracy is None:
        return None
    a = np.asarray(accuracy, dtype=float)
    valid = np.isfinite(a) & (a > 0)
    if not valid.any():
        return None
    w = np.zeros(len(a), dtype=float)
    w[valid] = 1.0 / (a[valid] ** 2)
    w[~valid] = w[valid].min()
    return w


def _weighted_mean(values: np.ndarray, mask: np.ndarray, weights) -> float:
    """Mean of ``values`` over the non-outlier ``mask``, accuracy-weighted by
    ``weights`` when available. Falls back to a plain mean (whole segment) when the
    mask is empty or the weights are unusable."""
    if not mask.any():
        mask = np.ones(len(values), dtype=bool)
    if weights is None:
        return float(values[mask].mean())
    w = weights[mask]
    if w.sum() <= 0:
        return float(values[mask].mean())
    return float(np.average(values[mask], weights=w))


# A "move" this short (few points, brief) sandwiched between two stops at the
# *same* place is GPS drift — a lone fix that jumped out of the stay and back — or
# a short cross-track gap token, not a real trip. Both bounds must hold so a
# genuine leave-and-return (drive round the block, back home) survives: a real
# loop has many points over minutes even though it ends where it began.
MOVE_COALESCE_MAX_S = 120   # seconds — max move duration to absorb
MOVE_COALESCE_MAX_PTS = 3   # points  — max move size to absorb


def _merge_stop_run(a: dict, m: dict, b: dict) -> dict:
    """Merge stop ``a`` + spurious move ``m`` + stop ``b`` (same place) into one
    stop spanning a.start … b.end. Keeps a's stop identity/place_id; blends the
    two stop centroids by point count (both are the same place, <~150 m apart)."""
    merged = dict(a)
    merged["end"] = b["end"]
    merged["end_ts"] = b["end_ts"]
    merged["end_lat"] = b["end_lat"]
    merged["end_lon"] = b["end_lon"]
    merged["end_alt"] = b["end_alt"]
    merged["n_points"] = a["n_points"] + m["n_points"] + b["n_points"]
    na, nb = a["n_points"], b["n_points"]
    if na + nb > 0:
        merged["centroid_lat"] = (a["centroid_lat"] * na + b["centroid_lat"] * nb) / (na + nb)
        merged["centroid_lon"] = (a["centroid_lon"] * na + b["centroid_lon"] * nb) / (na + nb)
    return merged


def coalesce_spurious_moves(segments: list[dict]) -> list[dict]:
    """Stitch ``stop(P) → shortMove → stop(P)`` back into one stop so a single
    drifted fix (or short gap token) can't split one visit into Place→move→Place.
    Only absorbs a move that is both brief and tiny (see the thresholds); a real
    leave-and-return trip is long/dense enough to survive. ``segments`` must be
    time-ordered. Chains, so stop-move-stop-move-stop at one place folds to one."""
    if len(segments) < 3:
        return segments
    segs = list(segments)
    i = 0
    while i + 2 < len(segs):
        a, m, b = segs[i], segs[i + 1], segs[i + 2]
        pid = a.get("place_id")
        is_blip_move = (
            bool(a["is_stop"]) and not bool(m["is_stop"]) and bool(b["is_stop"])
            and pid is not None and pid == b.get("place_id")
            and m["n_points"] <= MOVE_COALESCE_MAX_PTS
            and (m["end_ts"] - m["start_ts"]).total_seconds() <= MOVE_COALESCE_MAX_S
        )
        if is_blip_move:
            segs[i] = _merge_stop_run(a, m, b)
            del segs[i + 1:i + 3]   # stay at i to chain a following move
        else:
            i += 1
    return segs


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
                # Remove outliers from the segment before calculating centroid and other stats
                lat_vals = seg["latitude"].values
                lon_vals = seg["longitude"].values
                lat_mask = remove_outliers(lat_vals)
                lon_mask = remove_outliers(lon_vals)
                # Accuracy-weight the centroid by the horizontal accuracy radius
                # (1/accuracy²) so a few loose urban-canyon fixes don't drag a stop
                # off its true venue. None when accuracy is absent → plain mean,
                # matching prior behaviour.
                w = _accuracy_weights(seg["accuracy"].values) if "accuracy" in seg else None

                entry = {
                    "track_id":     track_id,
                    "start":        seg["formatted_time"].iloc[0],
                    "end":          seg["formatted_time"].iloc[-1],
                    "start_ts":     seg["timestamp"].iloc[0],
                    "end_ts":       seg["timestamp"].iloc[-1],
                    "is_stop":      seg["label_smooth"].iloc[0],
                    "centroid_lat": _weighted_mean(lat_vals, lat_mask, w),
                    "centroid_lon": _weighted_mean(lon_vals, lon_mask, w),
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

    # Sort segments by start time, then stitch away spurious drift moves that
    # split one visit into stop→move→stop at the same place.
    segments.sort(key=lambda x: x["start_ts"])
    segments = coalesce_spurious_moves(segments)
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
    # Memoize the flight decision per GPS gap (keyed by the right point's index).
    # Many consecutive images interpolate within the same (left, right) pair, and
    # is_flight_pair does two airport-polygon lookups — compute it once per gap.
    flight_gap_cache: dict[int, bool] = {}

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
                    # Flight hops curve over hundreds of km, so a straight lat/lon
                    # blend would place mid-flight images far off the real path.
                    # Slerp along the great circle instead when both ends are
                    # airports (or the hop is unambiguously airborne).
                    is_flight = flight_gap_cache.get(j)
                    if is_flight is None:
                        is_flight = tmode.is_flight_pair(
                            left["latitude"], left["longitude"],
                            right["latitude"], right["longitude"], total_gap,
                        )
                        flight_gap_cache[j] = is_flight
                    if is_flight:
                        lat_i, lon_i = tmode.great_circle_point(
                            left["latitude"], left["longitude"],
                            right["latitude"], right["longitude"], ratio,
                        )
                    else:
                        lat_i = left["latitude"] + ratio * (right["latitude"] - left["latitude"])
                        lon_i = left["longitude"] + ratio * (right["longitude"] - left["longitude"])
                    closest.update(
                        {
                            "latitude": lat_i,
                            "longitude": lon_i,
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
                logger.warning(
                    f"Warning: No GPS data to interpolate for image {image.image_path} at {img_ts}"
                )

        closest["image_id"] = image.id
        closest["image_path"] = image.image_path
        closest["gaps_s"] = gap_s.total_seconds()
        closest["date"] = date
        rows.append(closest)

    return rows


def _apply_timezone_to_images(session, tz_by_image_id: dict) -> int:
    """Overwrite Image.timezone with the GPS-derived zone and recompute every
    local wall-clock field (local_timestamp, year/month/day/hour,
    seconds_from_midnight, date) from the authoritative UTC Image.timestamp.

    Always overwrites — a stale capture-side timezone may already be stored from
    ingest, so we must not guard on the existing value being null. Shared by the
    live pipeline and backfill_image_timezone.py.
    """
    if not tz_by_image_id:
        return 0

    ids = list(tz_by_image_id.keys())
    utc_by_id = {
        r.id: r.timestamp
        for r in session.execute(select(Image.id, Image.timestamp).where(Image.id.in_(ids)))
    }

    updates = []
    for image_id, tz_name in tz_by_image_id.items():
        utc = utc_by_id.get(image_id)
        if utc is None:
            continue
        try:
            tz = ZoneInfo(tz_name)
        except (ZoneInfoNotFoundError, ValueError):
            # A malformed stored zone must skip its own row, not abort the batch.
            logger.warning("Skipping image %s: bad timezone %r", image_id, tz_name)
            continue
        local = utc.replace(tzinfo=timezone.utc).astimezone(tz)
        updates.append({

            "id": image_id,
            "timezone": tz_name,
            "local_timestamp": local,
            "year": local.year,
            "month": local.month,
            "day": local.day,
            "hour": local.hour,
            "seconds_from_midnight": local.hour * 3600 + local.minute * 60 + local.second,
            "date": local.strftime("%Y-%m-%d"),
        })

    if not updates:
        return 0

    # ORM bulk UPDATE by primary key: each dict carries "id" (the pk) + the
    # columns to set, no WHERE — same form as populate_locations.py.
    stmt = update(Image).execution_options(synchronize_session=None)
    for i in range(0, len(updates), 100):
        session.execute(stmt, updates[i:i + 100])
    return len(updates)


# ─── Step 8: Geocode segments → Location table ───────────────────────────────

# Buffer added around a segment's [start, end] when assigning images to it, so
# images captured just outside the GPS bounds still attach. The same window is
# reused for transport-mode assignment so an image's mode and location_id come
# from the same segment.
_SEG_IMG_PRE = timedelta(seconds=5)
_SEG_IMG_POST = timedelta(seconds=15)


def _prior_stop_poi(session, device, start_ts, end_ts, candidates: list[dict]) -> dict | None:
    """
    The gazetteer POI this stop was already resolved to on a previous run, if any.

    Disambiguation reads ``Image.activity`` labels, but those are written by the
    annotation Celery task fired *after* this pass runs — so on a fresh run the
    labels aren't there yet and the LLM can't pick. Without this, the enrich step
    would then fall back to the Nominatim nearest venue and *overwrite* a name a
    previous (annotated) run had already corrected, flipping e.g. a lab back to
    the frozen-yogurt shop next door. We look up the Location currently assigned
    to this stop's images and, when it matches one of the candidates by OSM
    element, return it so the earlier pick is preserved.
    """
    if start_ts is None or end_ts is None or not candidates:
        return None
    start_dt = start_ts.to_pydatetime() if hasattr(start_ts, "to_pydatetime") else start_ts
    end_dt = end_ts.to_pydatetime() if hasattr(end_ts, "to_pydatetime") else end_ts
    try:
        loc = session.execute(
            select(Location.osm_type, Location.osm_id)
            .join(Image, Image.location_id == Location.id)
            .where(Image.device == device)
            .where(Image.timestamp.between(start_dt, end_dt))
            .where(Location.stop.is_(True))
            .where(Location.osm_id.isnot(None))
            .group_by(Location.osm_type, Location.osm_id)
            .order_by(func.count().desc())
            .limit(1)
        ).first()
    except Exception as exc:
        logger.warning("prior stop POI lookup failed: %s", exc)
        return None
    if not loc:
        return None
    osm_type, osm_id = loc
    return next(
        (c for c in candidates
         if str(c.get("osm_id")) == str(osm_id) and c.get("osm_type") == osm_type),
        None,
    )


# Modes that mean the wearer arrived/left by a motorised vehicle: the generic
# GPS-only VEHICLE, every resolved sub-mode (bus/tram/train/ferry/cable_car/…), and
# FLIGHT (⇒ airport). Sub-modes must be included or a resolved "tram" leg would no
# longer read as transit here.
_TRANSIT_NEIGHBOUR_MODES = {tmode.VEHICLE, tmode.FLIGHT} | tmode.VEHICLE_SUBMODES


def _is_transit_waypoint(segments: list[dict], i: int) -> bool:
    """True when stop ``i`` is bracketed by a transit-capable move leg.

    A station/platform/terminal reads as a short stationary stop whose neighbour
    segment is a vehicle/flight leg (walking *inside* a venue has walk/stationary
    neighbours, so it won't trip this). Either side qualifies, so the first and
    last stop of a journey — reached on foot, left by tram, or vice-versa — count.
    """
    for j in (i - 1, i + 1):
        if 0 <= j < len(segments) and segments[j].get("mode") in _TRANSIT_NEIGHBOUR_MODES:
            return True
    return False


def _disambiguate_stop_poi(session, device, lat, lon, start_ts, end_ts, extra_candidates=None) -> dict | None:
    """
    Pick the venue a stop was actually in by matching its photos against nearby
    gazetteer candidates. Returns the chosen POI dict, or None to defer to the
    geocoder (no candidates, no images, or a sub-θ visual match).

    Non-regressing: once a stop has resolved to a gazetteer POI, a later run whose
    activity labels aren't ready yet (annotation runs async, after this pass) — or
    whose LLM call comes back ambiguous — reuses that prior POI instead of letting
    Nominatim's nearest-wins overwrite it. Only a *confident* LLM pick can move a
    stop to a different venue.
    """
    candidates = pgaz.nearby_pois(session, lat, lon)
    # Transit venues (stations/platforms/terminals) are fetched separately and only
    # when the caller passes them (neighbour-mode gate), so normal stops stay clean.
    if extra_candidates:
        seen = {(c.get("osm_type"), str(c.get("osm_id"))) for c in candidates}
        for c in extra_candidates:
            if (c.get("osm_type"), str(c.get("osm_id"))) not in seen:
                candidates.append(c)
    if not candidates:
        return None
    prior = _prior_stop_poi(session, device, start_ts, end_ts, candidates)
    activity_labels = pgaz.stop_activity_labels(session, device, start_ts, end_ts)
    if not activity_labels:
        return prior  # annotations not ready — keep the earlier pick, don't downgrade
    return pgaz.disambiguate_poi(candidates, activity_labels) or prior


def enrich_and_index_segments(
    session: Session,
    segments: list[dict],
    df: pd.DataFrame,
    device: str,
    date: str | None = None,
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
            # Visual disambiguation: pull nearby venues from the offline gazetteer
            # and let the stop's own photos pick which one, correcting a centroid
            # that drifted onto the shop next door. Falls through to Nominatim
            # when there are no candidates/images or the pick is below θ.
            # Neighbour-mode gate: if this stop sits between transit legs, also
            # offer nearby stations/platforms/terminals (kept out of the general
            # pool) so a tram stop / train station can win the disambiguation.
            transit_extra = None
            if _is_transit_waypoint(segments, i):
                transit_extra = pgaz.nearby_transit_pois(float(lat), float(lon))
                if transit_extra:
                    logger.info("Stop segment %d is a transit waypoint — added %d transit candidates",
                                i, len(transit_extra))
            poi = _disambiguate_stop_poi(
                session, device, float(lat), float(lon),
                seg.get("start_ts"), seg.get("end_ts"),
                extra_candidates=transit_extra,
            )
            stop = enrich_stop(float(lat), float(lon), poi=poi)
            stop_geos[i] = stop
            logger.info("Stop segment %d enriched to %s", i, stop.get("name"))

    # User-confirmed locations are stable within a run (only stop_correction sets
    # the flag, never enrich), so fetch them once instead of a correlated subquery
    # re-scanned on every pinned stop below.
    confirmed_loc_ids = session.execute(
        select(Location.id).where(Location.user_confirmed.is_(True))
    ).scalars().all()

    # Each located segment's (start_ts, end_ts, location_id), collected so a final
    # pass can assign holes to the nearest segment in time (see gap-fill below).
    seg_locations: list[tuple] = []

    # Every resolved stop segment (start, end, centroid, place_id, location_id),
    # persisted to gps_stop_segments so the timeline can show a stay even when no
    # photo was taken there. Only collected when `date` is known.
    stop_rows: list[dict] = []

    for i, seg in enumerate(segments):
        lat = seg.get("centroid_lat")
        lon = seg.get("centroid_lon")
        if lat is None or lon is None or pd.isna(lat) or pd.isna(lon):
            continue

        is_stop = bool(seg.get("is_stop"))
        start_ts = seg.get("start_ts")
        end_ts = seg.get("end_ts")

        # Respect a user's chat correction: if this stop's images are already
        # pinned to a user-confirmed Location, leave it untouched — don't
        # re-resolve the venue or reassign images (that clobbered the edit).
        if is_stop and start_ts is not None and end_ts is not None:
            s_dt = start_ts.to_pydatetime() if hasattr(start_ts, "to_pydatetime") else start_ts
            e_dt = end_ts.to_pydatetime() if hasattr(end_ts, "to_pydatetime") else end_ts
            pinned = session.execute(
                select(Location.id)
                .join(Image, Image.location_id == Location.id)
                .where(
                    Image.device == device,
                    Image.timestamp.between(s_dt - _SEG_IMG_PRE, e_dt + _SEG_IMG_POST),
                    Location.user_confirmed.is_(True),
                )
                .limit(1)
            ).scalar()
            if pinned:
                # Don't re-resolve the venue (that clobbered the edit), but DO
                # propagate the confirmed location across the whole stop window:
                #  - fill unassigned images, so a stay that grows past the
                #    already-corrected span (e.g. an evening at home that keeps
                #    extending) doesn't show newer images as "Unknown location".
                #  - overwrite stray *non-confirmed* labels, so a single drifted
                #    GPS fix that got a spurious "From X" move location mid-stop
                #    doesn't split off as a zero-duration "walking" blip inside
                #    the confirmed venue.
                # A DIFFERENT user-confirmed correction is never touched.
                filled = session.execute(
                    update(Image)
                    .where(Image.device == device)
                    .where(Image.timestamp.between(s_dt - _SEG_IMG_PRE, e_dt + _SEG_IMG_POST))
                    .where(or_(
                        Image.location_id.is_(None),
                        Image.location_id.notin_(confirmed_loc_ids),
                    ))
                    .values(location_id=pinned)
                )
                logger.info(
                    "Stop segment %d is user-confirmed — kept venue, propagated to %d images",
                    i, filled.rowcount,  # type: ignore
                )
                seg_locations.append((s_dt, e_dt, pinned))
                if date:
                    stop_rows.append({
                        "device": device, "date": date,
                        "start_time": s_dt, "end_time": e_dt,
                        "latitude": float(lat), "longitude": float(lon),
                        "place_id": seg.get("place_id"),
                        "timezone": find_timezone(float(lon), float(lat)),
                        "location_id": pinned,
                    })
                continue

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
                .where(Image.timestamp.between(start_dt - _SEG_IMG_PRE,
                                               end_dt + _SEG_IMG_POST))
                .values(location_id=location_id)
            )
            seg_locations.append((start_dt, end_dt, location_id))
            if date and is_stop:
                stop_rows.append({
                    "device": device, "date": date,
                    "start_time": start_dt, "end_time": end_dt,
                    "latitude": float(lat), "longitude": float(lon),
                    "place_id": seg.get("place_id"),
                    "timezone": tz,
                    "location_id": location_id,
                })

        logger.info(f"Upserted location {name} (stop={is_stop}) with key={key} and assigned to images between {start_ts} and {end_ts}")

    # ── Gap-fill: assign every still-unlocated image to the nearest segment ───────
    # The per-segment windows above (start-PRE .. end+POST) are NOT time-contiguous:
    # ~30 s GPS sampling + stop/move boundaries + dropped outliers leave 30 s–3 min
    # holes between segments. A photo captured in a hole matched no window and stayed
    # "Unknown location". Assign each remaining NULL image of the day to the segment
    # whose [start,end] interval is nearest in time, so coverage is gap-free. Only
    # touches images that are still NULL — strict + user-confirmed assignments stand.
    if seg_locations and len(df):
        day_start = df["timestamp"].min()
        day_end = df["timestamp"].max()
        ds = day_start.to_pydatetime() if hasattr(day_start, "to_pydatetime") else day_start
        de = day_end.to_pydatetime() if hasattr(day_end, "to_pydatetime") else day_end
        unlocated = session.execute(
            select(Image.id, Image.timestamp)
            .where(
                Image.device == device,
                Image.location_id.is_(None),
                Image.deleted == False,  # noqa: E712
                Image.timestamp.between(ds - _SEG_IMG_PRE, de + _SEG_IMG_POST),
            )
        ).all()
        by_loc: dict = defaultdict(list)
        for img_id, ts in unlocated:
            best_lid, best_gap = None, None
            for s_dt, e_dt, lid in seg_locations:
                if s_dt <= ts <= e_dt:
                    gap = 0.0
                elif ts < s_dt:
                    gap = (s_dt - ts).total_seconds()
                else:
                    gap = (ts - e_dt).total_seconds()
                if best_gap is None or gap < best_gap:
                    best_gap, best_lid = gap, lid
            if best_lid is not None:
                by_loc[best_lid].append(img_id)
        filled_total = 0
        for lid, ids in by_loc.items():
            session.execute(update(Image).where(Image.id.in_(ids)).values(location_id=lid))
            filled_total += len(ids)
        if filled_total:
            logger.info("Gap-fill: assigned %d unlocated images to their nearest segment", filled_total)

    # Persist stop segments for the day (replace-all so a re-run is idempotent),
    # so the timeline can render places with no photos. Deduped on (device,
    # start_time); collisions keep the last-seen window.
    if date:
        session.execute(
            delete(GpsStopSegment).where(
                GpsStopSegment.device == device,
                GpsStopSegment.date == date,
            )
        )
        seen: dict = {}
        for r in stop_rows:
            seen[(r["device"], r["start_time"])] = r
        if seen:
            session.execute(insert(GpsStopSegment), list(seen.values()))
        logger.info("Persisted %d GPS stop segments for %s/%s", len(seen), device, date)

    session.commit()

# ─── Step 7b: Transport mode per segment ─────────────────────────────────────


def _window_kinematics(
    ts: np.ndarray, lat: np.ndarray, lon: np.ndarray, alt: np.ndarray, start_ts, end_ts
) -> tuple[float, float, float, int]:
    """Main-trajectory kinematics over the [start_ts, end_ts] window of a
    *pre-sorted* GPS track: robust windowed speed (p85, m/s), net displacement
    (span, m), straightness (span / path-length) and the number of GPS points in
    the window (``n`` — how much the shape can be trusted).

    ``ts/lat/lon/alt`` are the whole track's numpy columns, sorted by ``ts``. The
    window is sliced with ``np.searchsorted`` (O(log N)), so classifying every
    image costs a binary search instead of a full-DataFrame mask + sort each call.

    Each p85 sample is the straight-line (chord) distance from a moving anchor to
    the first point at least ``MIN_SPEED_DT`` seconds ahead, divided by elapsed
    time — the window suppresses GPS jitter that otherwise fakes high
    consecutive-point speeds at walk pace, while p85 still picks up the genuinely
    fast stretches of vehicle travel.

    Span and straightness describe the *whole trajectory* rather than its fastest
    window: a real vehicle move covers ground in a fairly direct line (high span,
    straightness → 1), whereas spike noise on a stationary/walking stretch wanders
    in place (small span, straightness → 0). They let ``classify_segment_gps`` veto
    a spike-driven "vehicle" call — but only when ``n`` is large enough that the
    shape is meaningful (a 2–3 point window is too few to tell straight from winding).
    """
    lo_i = int(np.searchsorted(ts, np.datetime64(start_ts), side="left"))
    hi_i = int(np.searchsorted(ts, np.datetime64(end_ts), side="right"))
    n = hi_i - lo_i
    if n < 2:
        return 0.0, 0.0, 1.0, n
    lat, lon, alt, ts = lat[lo_i:hi_i], lon[lo_i:hi_i], alt[lo_i:hi_i], ts[lo_i:hi_i]
    span = haversine_distance(lat[0], lon[0], lat[-1], lon[-1], alt[0], alt[-1])
    # Cumulative path length (sum of consecutive hops) → straightness = span/path.
    path = 0.0
    for i in range(1, n):
        path += haversine_distance(lat[i - 1], lon[i - 1], lat[i], lon[i], alt[i - 1], alt[i])
    straightness = span / path if path > 0 else 1.0
    speeds = []
    anchor = 0
    for i in range(1, n):
        dt = (ts[i] - ts[anchor]) / np.timedelta64(1, "s")
        if dt < MIN_SPEED_DT:
            continue
        d = haversine_distance(lat[anchor], lon[anchor], lat[i], lon[i], alt[anchor], alt[i])
        speeds.append(d / dt)
        anchor = i
    # Window too short to fill one speed baseline: fall back to overall chord speed.
    if not speeds:
        dt = (ts[-1] - ts[0]) / np.timedelta64(1, "s")
        if dt <= 0:
            return 0.0, span, straightness, n
        return span / dt, span, straightness, n
    p85 = float(np.percentile(speeds, 85))
    return p85, span, straightness, n


def _window_ascent(g_ts: np.ndarray, g_alt: np.ndarray, start_ts, end_ts) -> float:
    """Total positive elevation gain (metres climbed) over the [start,end] window
    of the pre-sorted track — the tell for a cable car / funicular. Sums only the
    upward altitude steps, so a flat road trip returns ~0."""
    lo = int(np.searchsorted(g_ts, np.datetime64(start_ts), side="left"))
    hi = int(np.searchsorted(g_ts, np.datetime64(end_ts), side="right"))
    alt = g_alt[lo:hi]
    if len(alt) < 2:
        return 0.0
    diffs = np.diff(alt)
    return float(diffs[diffs > 0].sum())


def compute_segment_modes(
    session: Session,
    segments: list[dict],
    df: pd.DataFrame,
    device: str,
    date: str,
    image_rows: list[dict],
) -> None:
    """
    Set d["mode"] on each pending image row that doesn't already have a stored
    mode. One mode is computed per segment from its whole-trajectory GPS
    kinematics (stationary/walk/cycle/vehicle/flight) and applied to every image
    in that segment.

    Images whose ImageGPS row already has a *specific* stored mode are left
    untouched: they're skipped here and the upsert preserves the stored value via
    COALESCE. Images stored as the generic ``vehicle`` stay eligible so a later run
    can upgrade them to a sub-mode (tram/train/ferry/…) once the trip's photos have
    been annotated — the annotation LLM runs asynchronously, so the sub-mode is
    often not resolvable on the first pass. First-time/unset images are classified.
    """
    # Skip images that already carry a *specific* mode; keep generic-"vehicle" rows
    # eligible for a sub-mode upgrade on a later (post-annotation) run.
    already_moded: set = set(
        session.execute(
            select(ImageGPS.image_id)
            .join(Image, Image.id == ImageGPS.image_id)
            .where(
                Image.device == device, Image.date == date,
                ImageGPS.mode.isnot(None), ImageGPS.mode != tmode.VEHICLE,
            )
        ).scalars()
    )
    pending = [d for d in image_rows if d["image_id"] not in already_moded]
    if not pending:
        logger.info("No pending images to classify for device=%s date=%s", device, date)
        return

    # Map each pending image row to the segment it falls in. Prefer strict
    # [start, end] containment (the same span that set its location_id); only
    # fall back to the buffered window when no segment strictly contains it.
    # Buffered windows overlap (_SEG_IMG_PRE/_SEG_IMG_POST), so a first-match on the
    # buffer alone could grab an earlier neighbour than the locating segment.
    img_seg: dict = {}  # image_id -> segment index
    for d in pending:
        ts = pd.Timestamp(d["timestamp"])
        strict = None
        buffered = None
        for si, seg in enumerate(segments):
            if seg["start_ts"] <= ts <= seg["end_ts"]:
                strict = si
                break
            if buffered is None and (
                seg["start_ts"] - _SEG_IMG_PRE <= ts <= seg["end_ts"] + _SEG_IMG_POST
            ):
                buffered = si
        match = strict if strict is not None else buffered
        if match is not None:
            img_seg[d["image_id"]] = match

    # ── One GPS mode per segment (whole-segment kinematics) ──────────────────
    # Stops are stationary; moves are classified from the segment's whole
    # trajectory. Pre-extract the day's GPS track as sorted numpy columns ONCE so
    # each segment's kinematics is a binary-search slice (np.searchsorted in
    # _window_kinematics).
    track = df.sort_values("timestamp")
    g_ts = track["timestamp"].to_numpy()
    g_lat = track["latitude"].to_numpy()
    g_lon = track["longitude"].to_numpy()
    g_alt = (
        track["elevation"].fillna(0.0).to_numpy()
        if "elevation" in track else np.zeros(len(track))
    )

    seg_mode: dict = {}  # segment index -> mode (computed once per segment)
    for si in set(img_seg.values()):
        seg = segments[si]
        if seg.get("is_stop"):
            seg_mode[si] = tmode.STATIONARY
            continue
        flight = tmode.is_flight_pair(
            seg["start_lat"], seg["start_lon"],
            seg["end_lat"], seg["end_lon"],
            (seg["end_ts"] - seg["start_ts"]).total_seconds(),
        )
        p85, span, straightness, n_pts = _window_kinematics(
            g_ts, g_lat, g_lon, g_alt, seg["start_ts"], seg["end_ts"]
        )
        mode = tmode.classify_segment_gps(p85, span, flight, straightness, n_pts)
        # Refine a generic "vehicle" into a specific sub-mode (tram/train/bus/ferry/
        # cable_car/…) from the trip's photos — GPS speed can't tell them apart, the
        # photos can. Mirrors the stop-POI disambiguator. Deferred to segments the
        # GPS calls a vehicle, so a walk/cycle/flight is never second-guessed.
        # Refine a generic "vehicle" into a specific sub-mode (tram/train/bus/ferry/
        # cable_car/…) from the trip's photo activities — reusing the describe
        # annotation (text), no extra vision. On the first pass activities aren't
        # ready yet → stays generic; refine_segment_mode upgrades it post-annotation.
        if mode == tmode.VEHICLE:
            ascent = _window_ascent(g_ts, g_alt, seg["start_ts"], seg["end_ts"])
            labels = pgaz.stop_activity_labels(session, device, seg.get("start_ts"), seg.get("end_ts"))
            refined = tmode.disambiguate_vehicle_mode(labels, p85 * 3.6, ascent, straightness)
            if refined:
                mode = refined
        seg_mode[si] = mode
        logger.info(
            "Segment %d: mode %s (p85 %.1f, span %.1f m, straightness %.3f, n %d)",
            si, seg_mode[si], p85, span, straightness, n_pts,
        )

    # Stash each segment's mode on its dict so later passes (e.g. the enrich
    # transit-waypoint gate) can read a stop's neighbours' modes without a DB hit.
    for si, m in seg_mode.items():
        segments[si]["mode"] = m

    # Propagate each segment's mode to its images. Rows with no segment match get
    # no mode → insert NULL → reclassify next run (don't pin them to "unknown",
    # which the COALESCE upsert would make permanent).
    for d in pending:
        si = img_seg.get(d["image_id"])
        if si is not None:
            d["mode"] = seg_mode[si]


# Need at least this many GPS-carrying frames for a segment's kinematics to mean
# anything when refining its mode after annotation.
_SEGMENT_MODE_REFINE_MIN_PTS = 2


def _set_segment_mode(session, device, date, segment_id, new_mode) -> None:
    """Overwrite ImageGPS.mode → ``new_mode`` for every *moving* image of a segment
    (never touches a stationary/flight frame)."""
    session.execute(
        update(ImageGPS)
        .where(
            ImageGPS.image_id.in_(
                select(Image.id).where(
                    Image.device == device, Image.date == date,
                    Image.segment_id == segment_id,
                )
            ),
            ImageGPS.mode.in_(list(tmode.MOVE_MODES)),
            ImageGPS.mode != new_mode,
        )
        .values(mode=new_mode)
    )
    session.commit()


def refine_segment_mode(session: Session, device: str, date: str, segment_id: int) -> str | None:
    """
    Post-annotation refine of ONE segment's transport mode from its now-available
    photo activities. Called from ``describe_segment_task`` after the segment is
    described, so the specific mode resolves on a live day without a full re-run.

    Three mechanisms:
      1. **Explicit photo-named vehicle mode** — if the activity says ferry/train/
         tram/… the photos are authoritative: override ANY move mode, even walk/cycle.
         A slow ferry or tram sits in the walk/cycle GPS speed band and would otherwise
         stick as "cycle". No kinematics / finished-gate — the label alone is decisive.
      2. **Walk ↔ cycle correction from photos** — the GPS cycle band is narrow and
         walk-pace jitter routinely inflates a walk into "cycle". When the segment sits
         in the pedestrian band (walk/cycle) and the photos say the other one, trust the
         photos. Label-driven, so it runs even for a 1-frame sliver.
      3. **Generic vehicle → sub-mode via kinematics+LLM** — only for a segment the
         GPS called a generic ``vehicle`` with no explicit label, and only once the
         segment has *finished* (a later segment exists), so partial motion isn't
         judged mid-trip.

    Returns the new mode when it changed, else None.
    """
    rows = session.execute(
        select(
            Image.id, Image.timestamp,
            ImageGPS.latitude, ImageGPS.longitude, ImageGPS.elevation, ImageGPS.mode,
        )
        .join(ImageGPS, ImageGPS.image_id == Image.id)
        .where(
            Image.device == device, Image.date == date,
            Image.segment_id == segment_id, Image.deleted == False,
        )
        .order_by(Image.timestamp.asc())
    ).all()
    if not rows:
        return None

    modes = [r.mode for r in rows if r.mode]
    if not modes:
        return None
    dominant = Counter(modes).most_common(1)[0][0]
    if dominant not in tmode.MOVE_MODES:
        return None  # stationary / flight — never override

    seg_start, seg_end = rows[0].timestamp, rows[-1].timestamp
    labels = pgaz.stop_activity_labels(session, device, seg_start, seg_end)

    # 1. Explicit photo-named vehicle mode wins over the GPS speed class outright.
    explicit = next((m for lbl, _ in labels if (m := tmode.mode_from_activity(lbl))), None)
    if explicit and explicit != dominant:
        _set_segment_mode(session, device, date, segment_id, explicit)
        logger.info("Segment %s mode: %s → %s (from activity)", segment_id, dominant, explicit)
        return explicit

    # 2. Walk ↔ cycle correction: photos vote walk vs cycle; the majority wins over a
    # jitter-driven GPS band call. Confined to the pedestrian band, so a walking frame
    # on a vehicle trip can't demote the ride.
    if dominant in (tmode.WALK, tmode.CYCLE):
        votes: Counter = Counter()
        for lbl, n in labels:
            pm = tmode.pedestrian_mode_from_activity(lbl)
            if pm:
                votes[pm] += n
        if votes:
            ped = votes.most_common(1)[0][0]
            if ped != dominant:
                _set_segment_mode(session, device, date, segment_id, ped)
                logger.info("Segment %s mode: %s → %s (pedestrian photos)", segment_id, dominant, ped)
                return ped
        return None

    # 3. Generic vehicle with no explicit label → kinematics+LLM, once finished.
    if dominant != tmode.VEHICLE:
        return None
    if len(rows) < _SEGMENT_MODE_REFINE_MIN_PTS:
        return None
    later = session.execute(
        select(func.count()).select_from(Image).where(
            Image.device == device, Image.date == date,
            Image.segment_id.isnot(None), Image.segment_id != segment_id,
            Image.timestamp > seg_end,
        )
    ).scalar() or 0
    if later == 0:
        return None  # still the open tail of the day — refine on a later pass

    g_ts = np.array([np.datetime64(r.timestamp) for r in rows])
    g_lat = np.array([r.latitude for r in rows], dtype=float)
    g_lon = np.array([r.longitude for r in rows], dtype=float)
    g_alt = np.array([r.elevation if r.elevation is not None else 0.0 for r in rows], dtype=float)

    p85, _span, straightness, _n_pts = _window_kinematics(g_ts, g_lat, g_lon, g_alt, seg_start, seg_end)
    ascent = _window_ascent(g_ts, g_alt, seg_start, seg_end)
    refined = tmode.disambiguate_vehicle_mode(labels, p85 * 3.6, ascent, straightness)
    if not refined or refined == tmode.VEHICLE:
        return None
    _set_segment_mode(session, device, date, segment_id, refined)
    logger.info("Refined segment %s mode: vehicle → %s (%d frames)", segment_id, refined, len(rows))
    return refined


# ─── Persistence ──────────────────────────────────────────────────────────────

def _upsert_image_gps(session, rows: list[dict]) -> None:
    """Insert/update a batch of ImageGPS rows, preserving any already-stored mode —
    except a generic ``vehicle``, which a newly-resolved specific sub-mode
    (tram/train/ferry/…) is allowed to overwrite. Other stored modes stay put."""
    stmt = insert(ImageGPS).values(rows)
    # Keep the stored mode, unless it is the generic "vehicle" and the incoming row
    # carries a specific sub-mode — then upgrade. New rows (stored mode NULL) take
    # the incoming value as before.
    mode_expr = case(
        (
            (ImageGPS.mode == tmode.VEHICLE)
            & stmt.excluded.mode.isnot(None)
            & (stmt.excluded.mode != tmode.VEHICLE),
            stmt.excluded.mode,
        ),
        else_=func.coalesce(ImageGPS.mode, stmt.excluded.mode),
    )
    stmt = stmt.on_conflict_do_update(
        constraint="image_gps_image_id_key",
        set_={
            "latitude": stmt.excluded.latitude,
            "longitude": stmt.excluded.longitude,
            "elevation": stmt.excluded.elevation,
            "timestamp": stmt.excluded.timestamp,
            "timezone": stmt.excluded.timezone,
            "formatted_time": stmt.excluded.formatted_time,
            "source": stmt.excluded.source,
            "gap_s": stmt.excluded.gap_s,
            "mode": mode_expr,
        },
    )
    session.execute(stmt)


def _apply_activity_mode_overrides(session, device: str, date: str) -> int:
    """Photos are authoritative for the specific transport mode: where a segment's
    activity explicitly names one (ferry/train/tram/cable_car/…), override the GPS
    speed-derived ImageGPS.mode for that segment's moving frames — a slow ferry
    otherwise reads as cycling, a tram as a car. Runs over the whole day each full
    pipeline pass, so a forced re-run fixes already-annotated segments without needing
    to re-describe them. Only touches MOVE_MODES (never stationary/flight). Returns
    the number of ImageGPS rows changed."""
    seg_acts = session.execute(
        select(Image.segment_id, Image.activity).where(
            Image.device == device, Image.date == date, Image.deleted == False,
            Image.segment_id.isnot(None), Image.activity.isnot(None),
        ).distinct()
    ).all()
    updated = 0
    for seg_id, activity in seg_acts:
        explicit = tmode.mode_from_activity(activity)
        if not explicit:
            continue
        res = session.execute(
            update(ImageGPS).where(
                ImageGPS.image_id.in_(
                    select(Image.id).where(
                        Image.device == device, Image.date == date,
                        Image.segment_id == seg_id,
                    )
                ),
                ImageGPS.mode.in_(list(tmode.MOVE_MODES)),
                ImageGPS.mode != explicit,
            ).values(mode=explicit)
        )
        updated += res.rowcount or 0
    if updated:
        session.commit()
        logger.info("Activity mode overrides: %d ImageGPS rows for %s/%s", updated, device, date)
    return updated


# ─── Main ─────────────────────────────────────────────────────────────────────

def _day_gps_signature(session: Session, device: str, date: str, raw_df: pd.DataFrame) -> str:
    """Cheap fingerprint of a day's inputs — raw-GPS count + latest fix time + image
    count. When it is unchanged from the last successful run, re-running the pipeline
    would only re-geocode identical stops (re-hitting Nominatim/Overpass/LLM) and risk
    reverting a name a later annotated run had corrected. So we skip on a match."""
    raw_n = len(raw_df)
    raw_max = str(raw_df["timestamp"].max()) if raw_n else ""
    img_n = session.execute(
        select(func.count()).select_from(Image)
        .where(Image.device == device, Image.date == date, Image.deleted == False)
    ).scalar() or 0
    return f"{raw_n}:{raw_max}:{img_n}"


def run_pipeline(session: Session, device: str, date: str, modes_only: bool = False,
                 force: bool = False):
    """
    ``modes_only=True`` recomputes/refreshes only the per-segment transport mode (steps up to the ImageGPS mode upsert) and skips the slow tail — geocoding
    (enrich_and_index_segments) and segment annotation (load_all_segments). Used
    to backfill modes after the GPS-authoritative fusion change without
    re-hitting Nominatim/Overpass/LLM. Clear ImageGPS.mode first, else the
    COALESCE upsert keeps the stored value.

    ``force=True`` bypasses the unchanged-day skip guard — use it for a manual
    re-geocode (e.g. after a code change). The automatic live-GPS trigger leaves it
    False so a day whose GPS/images haven't changed is not reprocessed again and
    again (which needlessly re-geocodes and can revert corrected stop names).
    """
    logger.info(f"Processing device={device} date={date}")
    df = load_all_points(session, device, date)
    if len(df) == 0:
        logger.warning(f"No GPS data found for device={device} date={date}, skipping.")
        return

    # Skip when nothing about the day changed since the last successful full run.
    sig_key = f"gps_sig:{device}:{date}"
    sig = _day_gps_signature(session, device, date, df)
    if not modes_only and not force:
        try:
            if redis_client.get_value(sig_key) == sig.encode():
                logger.info("run_pipeline: %s/%s unchanged (sig=%s) — skipping", device, date, sig)
                return
        except Exception as _e:
            logger.debug("run_pipeline sig check failed for %s/%s: %s", device, date, _e)

    # 1b. Quality gate — drop fixes reporting a loose accuracy radius before any
    # track/stay processing, so junk never reaches stay detection or the filters.
    df = filter_low_accuracy(df)
    if len(df) == 0:
        logger.warning(f"All GPS fixes for device={device} date={date} failed the accuracy gate, skipping.")
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

    # 7b. Classify transport mode per segment (GPS kinematics + CLIP visual),
    # tagging each image row with its segment's mode.
    logger.debug(f"Computing transport modes for {len(segments)} segments and {len(data)} images")
    compute_segment_modes(session, segments, df, device, date, data)

    rows = []
    for d in data:
        if str(d["timezone"]) in ("None", "nan", ""):
            d["timezone"] = find_timezone(d["longitude"], d["latitude"])

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
                "mode": d.get("mode"),
            }
        )

        if len(rows) >= 100:
            _upsert_image_gps(session, rows)
            rows = []

    if rows:
        _upsert_image_gps(session, rows)

    # Update timezone + local wall-clock fields on each Image from the GPS-derived
    # zone. Always overwrite (no null-guard): the camera may have stored a stale
    # capture-side timezone at ingest, which left local_timestamp/date/hour wrong.
    tz_by_image_id = {}
    for d in data:
        tz = d["timezone"]
        if str(tz) in ("None", "nan", ""):
            tz = find_timezone(d["longitude"], d["latitude"])
        tz_by_image_id[d["image_id"]] = str(tz)
    _apply_timezone_to_images(session, tz_by_image_id)

    image_data.extend(data)
    session.commit()

    if modes_only:
        logger.info(f"modes_only: refreshed transport modes for device={device} date={date}")
        return

    # 8. Enriching segments with place info and indexing them for search.
    enrich_and_index_segments(session, segments, df, device, date=date)
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

    # Photos are authoritative for the specific mode: override the GPS speed class
    # wherever an already-stored activity names the mode (fixes a ferry stuck as
    # "cycle", a tram as "car"). Runs over the whole day, so a forced re-run corrects
    # existing annotated segments without re-describing them.
    try:
        _apply_activity_mode_overrides(session, device, date)
    except Exception as _e:
        session.rollback()
        logger.warning("activity mode overrides failed for %s/%s: %s", device, date, _e)

    # GPS clustering changed stops/locations, so the cached day summary (segment
    # locations + per-visit descriptions) is stale. Flag it for a full rebuild and
    # drop browse caches so the next day-summary request regenerates everything.
    try:
        from database.types import DaySummaryRecord
        from integrations.sessions.redis import bust_day_caches
        DaySummaryRecord.update_one(
            {"date": date, "device": device},
            data={"$set": {
                "updated": True,
                "text_summary_stale": True,
                "dirty_segment_ids": [],
                "segments": [],
            }},
            upsert=True,
        )
        bust_day_caches(device, date)
    except Exception as _e:
        logger.warning("run_pipeline: failed to invalidate day summary for %s/%s: %s", device, date, _e)

    # Record the day's input fingerprint so an identical later run is skipped.
    try:
        redis_client.set_value(sig_key, sig)
    except Exception as _e:
        logger.debug("run_pipeline: failed to store gps sig for %s/%s: %s", device, date, _e)

    logger.info(f"Finished processing device={device} date={date}")
    session.flush()

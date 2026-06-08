"""
bio_stats.py — per-day biometric aggregates.

Public API:
  hr_zone(bpm, max_hr) -> str
  compute_rmssd(ppi_ms) -> Optional[float]
  estimate_step_count(acc_rows) -> int
  detect_sleep(hr_rows, acc_rows, date) -> (start, end, minutes)
  compute_and_upsert_bio_day_stats(session, device_id, date) -> Optional[BioDayStats]
"""
from __future__ import annotations

import logging
import math
from datetime import datetime, timedelta
from typing import Optional

import numpy as np
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from database.models import (
    AccelerometerData,
    BioDayStats,
    HeartRateData,
    PPIData,
)

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# HR zones — Polar 5-zone model, thresholds expressed as % of max HR
# ---------------------------------------------------------------------------
_HR_ZONE_THRESHOLDS = [
    (0.90, "Max"),
    (0.80, "Hard"),
    (0.70, "Aerobic"),
    (0.60, "Light"),
    (0.00, "Rest"),
]


def hr_zone(bpm: float, max_hr: float = 190.0) -> str:
    frac = bpm / max_hr
    for threshold, label in _HR_ZONE_THRESHOLDS:
        if frac >= threshold:
            return label
    return "Rest"


# ---------------------------------------------------------------------------
# RMSSD — HRV metric from PPI (peak-to-peak) intervals
# ---------------------------------------------------------------------------
def compute_rmssd(ppi_ms: list[float]) -> Optional[float]:
    if len(ppi_ms) < 2:
        return None
    arr = np.array(ppi_ms, dtype=np.float32)
    diffs = np.diff(arr)
    return float(np.sqrt(np.mean(diffs ** 2)))


# ---------------------------------------------------------------------------
# Step count from accelerometer
# ---------------------------------------------------------------------------
_G_UNITS = 9.81   # m/s²; some sensors report in g (≈1.0)


def _infer_g(rows: list) -> float:
    """Detect whether sensor reports in m/s² or g by looking at mean magnitude."""
    sample = rows[:200]
    mags = [math.sqrt(r.x ** 2 + r.y ** 2 + r.z ** 2) for r in sample]
    mean_mag = float(np.mean(mags))
    # If mean is close to 1, sensor is in g units; if close to 9.8, m/s²
    return _G_UNITS if mean_mag > 5 else 1.0


def estimate_step_count(acc_rows: list) -> int:
    """
    Estimate daily step count from accelerometer rows.
    Uses zero-crossing count on the high-pass filtered magnitude.
    Each positive zero-crossing ≈ one step.
    """
    if len(acc_rows) < 4:
        return 0

    ts = np.array([r.time_stamp for r in acc_rows], dtype=np.float64)
    mag = np.array(
        [math.sqrt(r.x ** 2 + r.y ** 2 + r.z ** 2) for r in acc_rows],
        dtype=np.float32,
    )

    # Estimate sample rate
    gaps_ns = np.diff(ts)
    if len(gaps_ns) == 0:
        return 0
    median_gap = float(np.median(gaps_ns[gaps_ns > 0])) if np.any(gaps_ns > 0) else 0
    if median_gap <= 0:
        return 0
    fs = 1e9 / median_gap  # Hz

    # Subtract rolling mean (window = 2 s) to remove gravity (DC component)
    window = max(1, int(fs * 2))
    kernel = np.ones(window, dtype=np.float32) / window
    smoothed = np.convolve(mag, kernel, mode="same")
    ac = mag - smoothed  # AC = movement

    # Count upward zero-crossings
    crossings = int(np.sum((ac[:-1] < 0) & (ac[1:] >= 0)))
    return crossings


# ---------------------------------------------------------------------------
# Sleep detection
# ---------------------------------------------------------------------------
_SLEEP_MIN_MINUTES = 60  # don't count windows shorter than this

# Polar timestamp epoch offset (nanoseconds): Polar uses 2000-01-01 as epoch
_OLD_EPOCH_NS = int(datetime(1970, 1, 1).timestamp() * 1e9)
_POLAR_EPOCH_NS = int(datetime(2000, 1, 1).timestamp() * 1e9)
_DELTA_NS = _POLAR_EPOCH_NS - _OLD_EPOCH_NS


def _polar_ts_to_unix(ts_ns: int) -> float:
    return (ts_ns + _DELTA_NS) / 1e9


def detect_sleep(
    hr_rows: list,
    acc_rows: list,
    date: str,
) -> tuple[Optional[datetime], Optional[datetime], int]:
    """
    Find the primary sleep window for `date`.

    Scans 21:00 the previous evening to 12:00 noon on `date`.
    Sleep = contiguous window ≥ 60 min where:
      - avg HR/min ≤ (median daily HR + 5 bpm)
      - avg ACC magnitude/min is within 10% of g (lying still)

    Returns (sleep_start, sleep_end, total_sleep_minutes).
    """
    if not hr_rows or not acc_rows:
        return None, None, 0

    date_dt = datetime.strptime(date, "%Y-%m-%d")
    g_val = _infer_g(acc_rows)

    # Build per-minute index for HR
    hr_by_minute: dict[int, list[float]] = {}
    for row in hr_rows:
        unix_s = _polar_ts_to_unix(row.time_stamp)
        minute = int(unix_s // 60)
        hr_by_minute.setdefault(minute, []).append(float(row.hr))

    all_hr = [v for vals in hr_by_minute.values() for v in vals]
    if not all_hr:
        return None, None, 0
    median_hr = float(np.median(all_hr))
    rest_threshold = median_hr + 5

    # Build per-minute index for ACC
    acc_by_minute: dict[int, list[float]] = {}
    for row in acc_rows:
        unix_s = _polar_ts_to_unix(row.time_stamp)
        minute = int(unix_s // 60)
        mag = math.sqrt(row.x ** 2 + row.y ** 2 + row.z ** 2)
        acc_by_minute.setdefault(minute, []).append(mag)

    still_tol = 0.10 * g_val  # within 10% of g = still

    # Scan window: 21:00 yesterday → 12:00 today
    scan_start = int((date_dt - timedelta(hours=3)).timestamp() // 60)
    scan_end = int((date_dt + timedelta(hours=12)).timestamp() // 60)

    best_start: Optional[int] = None
    best_end: Optional[int] = None
    best_len = 0
    run_start: Optional[int] = None
    run_end: Optional[int] = None

    for minute in range(scan_start, scan_end):
        hrs = hr_by_minute.get(minute, [])
        accs = acc_by_minute.get(minute, [])

        hr_ok = (float(np.mean(hrs)) <= rest_threshold) if hrs else False
        acc_ok = (abs(float(np.mean(accs)) - g_val) <= still_tol) if accs else False

        if hr_ok and acc_ok:
            if run_start is None:
                run_start = minute
            run_end = minute
        else:
            if run_start is not None and run_end is not None:
                length = run_end - run_start + 1
                if length > best_len:
                    best_len = length
                    best_start, best_end = run_start, run_end
            run_start = run_end = None

    # flush last run
    if run_start is not None and run_end is not None:
        length = run_end - run_start + 1
        if length > best_len:
            best_len = length
            best_start, best_end = run_start, run_end

    if best_len < _SLEEP_MIN_MINUTES or best_start is None:
        return None, None, 0

    return (
        datetime.fromtimestamp(best_start * 60),
        datetime.fromtimestamp(best_end * 60),
        best_len,
    )


# ---------------------------------------------------------------------------
# Per-date window helpers
# ---------------------------------------------------------------------------
def _date_ns_window(date: str) -> tuple[int, int]:
    """Return (start_ns, end_ns) in Polar epoch (nanoseconds) for a date."""
    date_dt = datetime.strptime(date, "%Y-%m-%d")
    # Convert to Polar epoch: subtract DELTA
    start_unix_ns = int(date_dt.timestamp() * 1e9)
    start_polar_ns = start_unix_ns - _DELTA_NS
    end_polar_ns = start_polar_ns + int(86400 * 1e9)
    return start_polar_ns, end_polar_ns


# ---------------------------------------------------------------------------
# Main compute + upsert
# ---------------------------------------------------------------------------
def compute_and_upsert_bio_day_stats(
    session: Session,
    device_id: str,
    date: str,
) -> Optional[BioDayStats]:
    """
    Compute all biometric aggregates for device_id/date and upsert into bio_day_stats.
    Returns the upserted row, or None if there is no HR data for that day.
    """
    start_ns, end_ns = _date_ns_window(date)

    # HR
    hr_rows = session.execute(
        select(HeartRateData)
        .where(
            HeartRateData.device_id == device_id,
            HeartRateData.time_stamp >= start_ns,
            HeartRateData.time_stamp < end_ns,
        )
        .order_by(HeartRateData.time_stamp.asc())
    ).scalars().all()

    if not hr_rows:
        logger.debug("No HR data for %s on %s; skipping bio_day_stats.", device_id, date)
        return None

    hr_vals = np.array([r.hr for r in hr_rows], dtype=np.float32)
    avg_hr = float(np.mean(hr_vals))
    max_hr = float(np.max(hr_vals))
    resting_hr = float(np.percentile(hr_vals, 5))

    # HRV from PPI
    ppi_rows = session.execute(
        select(PPIData)
        .where(
            PPIData.device_id == device_id,
            PPIData.time_stamp >= start_ns,
            PPIData.time_stamp < end_ns,
        )
        .order_by(PPIData.time_stamp.asc())
    ).scalars().all()

    rmssd_val = compute_rmssd([float(r.ppi) for r in ppi_rows]) if ppi_rows else None

    # Steps from ACC
    acc_rows = session.execute(
        select(AccelerometerData)
        .where(
            AccelerometerData.device_id == device_id,
            AccelerometerData.time_stamp >= start_ns,
            AccelerometerData.time_stamp < end_ns,
        )
        .order_by(AccelerometerData.time_stamp.asc())
    ).scalars().all()

    step_count = estimate_step_count(list(acc_rows))

    # Sleep
    sleep_start, sleep_end, sleep_minutes = detect_sleep(
        list(hr_rows), list(acc_rows), date
    )

    logger.info(
        "BioDayStats %s/%s: avg_hr=%.1f resting=%.1f max=%.1f rmssd=%s steps=%d sleep=%dmin",
        device_id, date, avg_hr, resting_hr, max_hr,
        f"{rmssd_val:.1f}" if rmssd_val is not None else "n/a",
        step_count, sleep_minutes,
    )

    now = datetime.utcnow()
    stmt = (
        insert(BioDayStats)
        .values(
            device_id=device_id,
            date=date,
            avg_hr=avg_hr,
            resting_hr=resting_hr,
            max_hr=max_hr,
            rmssd=rmssd_val,
            step_count=step_count,
            sleep_start=sleep_start,
            sleep_end=sleep_end,
            sleep_minutes=sleep_minutes,
            computed_at=now,
        )
        .on_conflict_do_update(
            constraint="uq_bio_day_stats_device_date",
            set_={
                "avg_hr": avg_hr,
                "resting_hr": resting_hr,
                "max_hr": max_hr,
                "rmssd": rmssd_val,
                "step_count": step_count,
                "sleep_start": sleep_start,
                "sleep_end": sleep_end,
                "sleep_minutes": sleep_minutes,
                "computed_at": now,
            },
        )
    )
    session.execute(stmt)
    session.commit()

    return session.execute(
        select(BioDayStats).where(
            BioDayStats.device_id == device_id,
            BioDayStats.date == date,
        )
    ).scalars().first()


# ---------------------------------------------------------------------------
# Attach bio overlay to a list of SummarySegments
# ---------------------------------------------------------------------------
def attach_bio_to_segments(
    segments: list,
    hr_rows: list,
    max_hr: float = 190.0,
) -> list:
    """
    Given a list of SummarySegment objects and the day's HR rows,
    attach avg_hr and hr_zone to each segment in-place. Returns the list.
    """
    if not hr_rows or not segments:
        return segments

    # Build per-unix-minute HR lookup
    by_minute: dict[int, list[float]] = {}
    for row in hr_rows:
        unix_s = _polar_ts_to_unix(row.time_stamp)
        minute = int(unix_s // 60)
        by_minute.setdefault(minute, []).append(float(row.hr))

    for seg in segments:
        start_min = int(seg.start_time.timestamp() // 60)
        end_min = int(seg.end_time.timestamp() // 60)
        hr_vals = []
        for m in range(start_min, end_min + 1):
            hr_vals.extend(by_minute.get(m, []))
        if hr_vals:
            seg_avg_hr = float(np.mean(hr_vals))
            seg.avg_hr = round(seg_avg_hr, 1)
            seg.hr_zone = hr_zone(seg_avg_hr, max_hr)

    return segments

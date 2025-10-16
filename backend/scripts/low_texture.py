from __future__ import annotations
import os

from pathlib import Path
from typing import List, Tuple, Set, Dict, Any
import cv2
import numpy as np
import pandas as pd
from PIL import Image, ExifTags
from tqdm import tqdm
from constants import DIR

CSV_PATH = Path("files/pocket_score.csv")  # same pattern as your visual_density.csv

# ---------- feature helpers ----------

def _image_entropy(gray: np.ndarray) -> float:
    hist = cv2.calcHist([gray],[0],None,[256],[0,256]).ravel()
    p = hist / (hist.sum() + 1e-9)
    # avoid log(0)
    return float(-np.sum(np.where(p>0, p*np.log2(p), 0.0)))

def _edge_density(gray: np.ndarray) -> float:
    edges = cv2.Canny(gray, 50, 150, L2gradient=True)
    return float(np.count_nonzero(edges)) / float(edges.size)

def _read_exif_iso_exp(path: str) -> Tuple[int | None, float | None]:
    try:
        ex = Image.open(f"{DIR}/{path}").getexif()
        if not ex:
            return None, None
        tagmap = {ExifTags.TAGS.get(k,k):v for k,v in ex.items()}
        iso = tagmap.get('ISOSpeedRatings') or tagmap.get('PhotographicSensitivity')
        exp = tagmap.get('ExposureTime')
        if isinstance(exp, tuple) and exp[1] != 0:
            exp = exp[0] / exp[1]
        return iso if isinstance(iso, int) else None, float(exp) if exp else None # type: ignore
    except Exception:
        return None, None

def _compute_features(bgr: np.ndarray) -> Dict[str, float]:
    # downscale for speed
    h, w = bgr.shape[:2]
    scale = max(1, int(min(h, w)/160))
    if scale > 1:
        bgr = cv2.resize(bgr, (w//scale, h//scale), interpolation=cv2.INTER_AREA)

    hsv = cv2.cvtColor(bgr, cv2.COLOR_BGR2HSV)
    v = hsv[:,:,2]
    gray = cv2.cvtColor(bgr, cv2.COLOR_BGR2GRAY)

    mean_v = float(v.mean())
    std_v  = float(v.std())
    lap_var = float(cv2.Laplacian(gray, cv2.CV_64F).var())
    ent = _image_entropy(gray)
    edens = _edge_density(gray)
    return {
        "mean_v": mean_v,
        "std_v": std_v,
        "laplacian_var": lap_var,
        "entropy": ent,
        "edge_density": edens,
    }

def _covered_rule(feats: Dict[str, float],
                  iso: int | None,
                  exp: float | None,
                  thr_dark: float = 18,
                  thr_std: float = 10,
                  thr_lap: float = 15,
                  thr_edge: float = 0.002,
                  thr_entropy: float = 3.0) -> Tuple[bool, float]:
    """Return (covered?, score). Score is a simple confidence 0..10."""
    dark = feats["mean_v"] < thr_dark and feats["std_v"] < thr_std
    texture_low = (feats["laplacian_var"] < thr_lap) or (feats["edge_density"] < thr_edge)
    lowinfo = feats["entropy"] < thr_entropy
    exif_hint = bool(iso and exp and iso >= 800 and exp >= (1/60) and feats["mean_v"] < 24)

    covered = (dark and (texture_low or lowinfo)) or exif_hint

    # crude confidence score: higher = more likely covered
    score = 0.0
    score += 4.0 if dark else 0.0
    score += 3.0 if texture_low else 0.0
    score += 2.0 if lowinfo else 0.0
    score += 1.0 if exif_hint else 0.0
    return covered, min(10.0, score)

# ---------- your-style CSV pass ----------

def check_all_files_for_pocket(image_paths: List[str]) -> None:
    """
    Scan only new images, compute features + pocket score, and persist to CSV.
    Mirrors your check_all_files(...) pattern.
    """
    print(f"Checking {len(image_paths)} images for pocket/covered-lens...")
    existing_df: pd.DataFrame | None = None
    existing_images: Set[str] = set()

    if CSV_PATH.exists():
        existing_df = pd.read_csv(CSV_PATH)
        existing_images = set(existing_df["image"].tolist())

    new_paths = [p for p in image_paths if p not in existing_images]
    rows: List[Dict[str, Any]] = []

    for p in tqdm(new_paths, disable=not new_paths):
        try:
            bgr = cv2.imread(f"{DIR}/{p}", cv2.IMREAD_COLOR)
            if bgr is None:
                continue
            feats = _compute_features(bgr)
            iso, exp = _read_exif_iso_exp(p)
            covered, score = _covered_rule(feats, iso, exp)
            rows.append({
                "image": p,
                **feats,
                "iso": iso if iso is not None else np.nan,
                "exposure": exp if exp is not None else np.nan,
                "score": score,
                "covered": bool(covered),
            })
        except Exception as e:
            print(f"Error processing {p}: {e}")

    if rows:
        df = pd.DataFrame(rows)
        if existing_df is not None:
            df = pd.concat([existing_df, df], ignore_index=True)
            df = df.drop_duplicates(subset=["image"], keep="last")
        df.to_csv(CSV_PATH, index=False)
    else:
        print("No new images were processed.")

def get_pocket_indices(
    image_paths: List[str],
    *,
    min_streak_len: int = 3,
    keep_one_per_streak: bool = True,
    score_threshold: float = 3.0,
) -> Tuple[np.ndarray, Set[str]]:
    """
    Returns:
      indices_to_delete: np.ndarray[int] of positions in image_paths
      images_set: set[str] of absolute paths slated for deletion
    """
    check_all_files_for_pocket(image_paths)

    if not CSV_PATH.exists():
        return np.array([], dtype=int), set()

    df = pd.read_csv(CSV_PATH)
    score_map: Dict[str, float] = dict(zip(df["image"], df["score"]))
    covered_map: Dict[str, bool] = dict(zip(df["image"], df["covered"]))

    # align with input ordering
    flags = []
    for p in image_paths:
        # fallback to a high score (not covered) if missing
        s = score_map.get(p, 0.0)
        c = covered_map.get(p, s >= score_threshold)  # if no boolean, use score
        if "20250919_114114" in p:
            print(f"DEBUG: {p} -> score {s}, covered {c}")
        flags.append(bool(c) or (s >= score_threshold))

    indices_to_delete = np.where(flags)[0].tolist()
    return np.array(indices_to_delete, dtype=int), {image_paths[i] for i in indices_to_delete}

    # # collapse consecutive detections into streaks
    # indices_to_delete: List[int] = []
    # n = len(flags)
    # i = 0
    # while i < n:
    #     if not flags[i]:
    #         i += 1
    #         continue
    #     j = i
    #     while j < n and flags[j]:
    #         j += 1
    #     streak_len = j - i
    #     if streak_len >= min_streak_len:
    #         # delete whole streak or keep the first, per preference
    #         start = i + (1 if keep_one_per_streak else 0)
    #         indices_to_delete.extend(range(start, j))
    #     i = j

    images_set = {image_paths[k] for k in indices_to_delete}
    return np.array(indices_to_delete, dtype=int), images_set



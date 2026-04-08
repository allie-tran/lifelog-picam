import os
import bisect
from datetime import timedelta
from typing import Counter

import clip
import pandas as pd
import torch
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session
from tqdm import tqdm
from dotenv import load_dotenv

from models import Image, ImageEmbedding, CLIPEmbedding

GPS_FILE = "files/annotated_points.csv"
DEVICE_ID = "cathal"

load_dotenv()
PG_URI = os.getenv("PG_URI", "postgresql://postgres:password@localhost:5432/lsc24")
engine = create_engine(PG_URI)
session = Session(bind=engine.connect())

CHECKPOINT_PATH = "../conclip_vit_l14.pt"
DEVICE = "cuda" if torch.cuda.is_available() else "cpu"

# -- --- CLIP MODEL LOADING --- ---


def load_checkpoint(model, checkpoint_path):
    ckpt = torch.load(checkpoint_path, weights_only=False)
    model = model.float()
    model.load_state_dict(ckpt["model"])
    return model


def load_model():
    # model, preprocess = clip.load("ViT-L/14", device=DEVICE)
    # model = load_checkpoint(model, CHECKPOINT_PATH)
    model, preprocess = clip.load("ViT-L/14@336px", device=DEVICE)
    model.float()
    model.eval()
    model = model.to(DEVICE)
    return model, preprocess


def predict(model, texts, features):
    with torch.no_grad():
        text_inputs = clip.tokenize(texts).to(DEVICE)
        text_features = model.encode_text(text_inputs)
        text_features /= text_features.norm(dim=-1, keepdim=True)

        similarity = (text_features @ features.T).cpu().numpy()
        return similarity


# -- --- GPS TO IMAGE ANNOTATION --- ---
def assign_gps_to_images(date, points, point_timestamps):
    # Assign GPS data to images
    images = session.execute(
        select(Image.id, Image.image_path, Image.timestamp).where(
            Image.device == DEVICE_ID,
            Image.date == date,
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
                    }
                )
            else:
                print(
                    f"Warning: No GPS data to interpolate for image {image.image_path} at {img_ts}"
                )

        closest["image_path"] = image.image_path
        closest["gaps_s"] = gap_s.total_seconds()
        closest["date"] = date
        rows.append(closest)

    return rows


# -- --- MOVEMENT TYPE ANNOTATION --- ---

MOVES = {
    "I am sitting on an airplane": "Airplane",
    "I am in a car": "Car",
    "I am in an airport": "Inside",
    "I am cycling": "Cycling",
    "I am walking outside or on the street": "Walking Outside",
    "I am on public transport": "Public Transport",
    "I am inside a building or a house": "Inside",
}

INSIDES = {
    "I am inside a building or a house": "Inside",
    "I am outside": "Outside",
    "I am in a transport": "Transport",
}

import os

import numpy as np
from tqdm.auto import tqdm


def get_text_features(model):
    text_moves = list(MOVES.keys())
    text_insides = list(INSIDES.keys())
    texts = text_moves + text_insides
    with torch.no_grad():
        text_inputs = clip.tokenize(texts).to(DEVICE)
        text_features = model.encode_text(text_inputs)
        text_features /= text_features.norm(dim=-1, keepdim=True)
    nm = len(text_moves)
    return text_features, text_moves, text_insides, nm


if __name__ == "__main__":
    # 1. Load GPS points
    csv_file = "files/annotated_points.csv"
    df_points = pd.read_csv(csv_file)
    df_points["timestamp"] = pd.to_datetime(df_points["timestamp"], format="ISO8601")
    # remove timezone info for easier comparison (assuming all timestamps are in UTC)
    df_points["timestamp"] = df_points["timestamp"].dt.tz_localize(None)

    point_timestamps = df_points["timestamp"].tolist()  # this is a datetime object
    all_points = df_points.to_dict(orient="records")
    print(f"Loaded {len(all_points)} GPS points from {csv_file}")

    # 2. Get unique dates from image timestamp (formatted as YYYY-MM-DD)
    df_points["date"] = df_points["timestamp"].dt.date
    dates = df_points["date"].unique()
    dates = sorted(dates)

    # 3. For each date, assign GPS data to images and collect results
    image_data = []
    for date in tqdm(dates):
        date_str = date.strftime("%Y-%m-%d")
        image_data += assign_gps_to_images(date_str, all_points, point_timestamps)
    print(f"Assigned GPS data to {len(image_data)} images across {len(dates)} dates")

    # 4. Add movement type
    model, preprocess = load_model()
    text_features, text_moves, text_insides, nm = get_text_features(model)
    image_to_movement = {}
    image_to_inside = {}
    for date in tqdm(dates):
        records = session.execute(
            select(CLIPEmbedding.embedding, Image.image_path)
            .join(Image.clip_embedding)
            .where(Image.device == DEVICE_ID, Image.date == date.strftime("%Y-%m-%d"))
        )
        records = list(records)
        features = [f.embedding for f in records]
        valids = [f.image_path for f in records]
        if not features:
            continue

        image_features = np.stack(features)
        image_features = torch.tensor(image_features).to(DEVICE)
        image_features /= image_features.norm(dim=-1, keepdim=True)

        similarity = (text_features @ image_features.T).cpu().numpy()
        sim_move = similarity[:nm, :]
        sim_inside = similarity[nm:, :]

        best_move_idxs = np.argmax(sim_move, axis=0)
        best_inside_idxs = np.argmax(sim_inside, axis=0)

        for img_path, move_idx, inside_idx in zip(
            valids, best_move_idxs, best_inside_idxs
        ):
            image_to_movement[img_path] = MOVES[text_moves[move_idx]]
            image_to_inside[img_path] = INSIDES[text_insides[inside_idx]]

    # Add movement labels to image_data
    for d in image_data:
        img_path = d["image_path"]
        d["movement"] = image_to_movement.get(img_path, "Unknown")
        d["inside_outside"] = image_to_inside.get(img_path, "Unknown")
    print(
        f"Annotated movement type for {len(image_to_movement)} images and inside/outside for {len(image_to_inside)} images"
    )

    # 4. Save results to CSV
    df = pd.DataFrame(image_data)
    # Reorder columns for output
    columns = [
        "segment_id",
        "image_path",
        "timestamp",
        "latitude",
        "longitude",
        "elevation",
        "movement",
        "inside_outside",
        "interpolated",
        "gaps_s",
        "source_file",
    ]
    df = df[columns]
    df = df.sort_values("timestamp")
    df.to_csv("files/image_gps.csv", index=False)
    print("\nSaved → image_gps.csv")

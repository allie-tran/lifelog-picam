import pandas as pd
import numpy as np
import os
from typing import Dict, List
from PIL import Image
from constants import DIR
from app_types import AppFeatures

import torch
from torch import nn
import torchvision.transforms as T
from copy import deepcopy

from timm import create_model
from timm.data.constants import IMAGENET_DEFAULT_MEAN, IMAGENET_DEFAULT_STD
from tqdm.auto import tqdm

base_model_name = "hf_hub:timm/convnext_tiny.fb_in22k"
device = 'cuda' if torch.cuda.is_available() else 'cpu'
base_model = create_model(base_model_name, pretrained=True).to(device)

children = list(base_model.children())

relevant = children[:-1].copy()
first_layers = list(children[-1].children())[:-2]
relevant.append(torch.nn.Sequential(*first_layers))
relevant.append(nn.Linear(768, 2048, bias = True))
relevant.append(nn.GELU())
relevant.append(nn.Linear(2048, 1, bias = True))

model = torch.nn.Sequential(*relevant).to(device)

state = torch.load('files/visual_density.pt', map_location=torch.device('cpu'))

# Fix the state_dict
state_dict = deepcopy(state['state_dict'])
for name, param in state['state_dict'].items():
    if name.startswith('3.norm'):
        state_dict[name.replace("3.norm", "3.1")] = state_dict.pop(name)

model.load_state_dict(state_dict)

NORMALIZE_MEAN = IMAGENET_DEFAULT_MEAN
NORMALIZE_STD = IMAGENET_DEFAULT_STD
SIZE = 256

transforms = [
    T.Resize(SIZE, interpolation=T.InterpolationMode.BICUBIC),
    T.ToTensor(),
    T.Normalize(NORMALIZE_MEAN, NORMALIZE_STD),
]
transforms = T.Compose(transforms)


def get_score(image_path):
    img = Image.open(f"{DIR}/{image_path}").convert('RGB')
    img_tensor = transforms(img).unsqueeze(0)  # type: ignore

    with torch.no_grad():
        img_tensor = img_tensor.to(device)
        prediction = model(img_tensor).cpu().numpy()[0][0]

    return prediction


def check_all_files(image_paths: List[str]):
    print("-" * 20)
    print(f"Checking images for visual density...")
    existing_df = None
    existing_images = set()

    # Load previously computed scores if available
    if os.path.exists(f"files/visual_density.csv"):
        existing_df = pd.read_csv(f"files/visual_density.csv")
        existing_images = set(existing_df["image"].tolist())
        print(f"Found {len(existing_images)} existing visual density scores.")
        print(list(existing_images)[:5])

    # Only process new images
    # Flatten image_paths
    paths = [p for p in image_paths if p not in existing_images]
    print(f"Processing {len(paths)} new images for visual density...")
    print(paths[:5])
    scores = []

    pbar = tqdm(total=len(paths), desc="Computing visual density scores")
    for photo_path in paths:
        pbar.update(1)
        pbar.set_description(f"Processing {photo_path}")
        try:
            score = get_score(photo_path)
            scores.append({"image": photo_path, "score": score})
        except Exception as e:
            print(f"Error processing {photo_path}: {e}")

    # Save results to a CSV file
    if scores:
        df = pd.DataFrame(scores)
        if existing_df is not None:
            df = pd.concat([existing_df, df], ignore_index=True)
            df = df.drop_duplicates(subset=["image"])
        df.to_csv(f"files/visual_density.csv", index=False)
    else:
        print("No images were processed.")

    print("-" * 20)


def get_low_visual_density_indices(features: AppFeatures):
    image_paths = {}
    all_paths = []
    for device_id in features.keys():
        paths = features[device_id]["siglip"].image_paths
        image_paths[device_id] = paths
        all_paths.extend(
            [f"{device_id}/{path}" for path in paths]
        )
    check_all_files(all_paths)

    # return the indices of the images with lowest visual density scores
    if not os.path.exists(f"files/visual_density.csv"):
        return np.array([])
    df = pd.read_csv(f"files/visual_density.csv")
    score_dict = dict(zip(df["image"], df["score"]))
    # scores = [score_dict.get(path, 10) for path in image_paths]  # default to 10 if not found
    all_indices = {}
    all_images_with_low_density = set()

    for device in image_paths:
        scores = [score_dict.get(f"{device}/{path}", 10) for path in image_paths[device]]

        indices = [i for i, score in enumerate(scores) if score < 8]
        all_indices[device] = indices
        all_images_with_low_density.update(
            {f"{device}/{image_paths[device][i]}" for i in indices}
        )
        print(f"Device {device}: Found {len(indices)} images with low visual density.")
    return all_indices, all_images_with_low_density

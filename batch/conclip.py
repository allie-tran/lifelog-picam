import clip
import torch
from PIL import Image
import numpy as np
import glob
import os
import math
import pandas as pd
from pathlib import Path
from tqdm import tqdm

# the .pt file downloaded from the links above
device = "cuda"

checkpoint_path = "conclip_vit_l14.pt"
# the .pt file downloaded from the links above
device = "cuda"
def load_checkpoint(model, checkpoint_path):
	ckpt = torch.load(checkpoint_path, weights_only=False)
	model = model.float()
	model.load_state_dict(ckpt["model"])
	return model

class ConCLIPBinaryClassifier:
    def __init__(self, model_path="conclip_vit_l14.pt", device="cuda"):
        self.device = device
        self.model, self.preprocess = clip.load("ViT-L/14", device=device)
        self.model = load_checkpoint(self.model, model_path)
        self.model = self.model.to(device)

    def predict(self, positive_query: str, negative_query: str, image_features: list[np.array]):
        texts = [positive_query, negative_query]
        texts_tokenized = clip.tokenize(texts).to(self.device)

        with torch.no_grad():
            text_features = self.model.encode_text(texts_tokenized)
            text_features /= text_features.norm(dim=-1, keepdim=True)

            image_tensor = torch.tensor(image_features).to(self.device)
            image_tensor /= image_tensor.norm(dim=-1, keepdim=True)

            sim = (100 * image_tensor @ text_features.T).softmax(dim=-1)

        # Return probabilities for the positive class
        return sim[:, 0].cpu().numpy()

    def compute_clip_features(self, photo_batches: list[str]):
        # Load all the photos from the files
        photos = []
        okay_files = []
        photos_processed = []
        for photo_file in photo_batches:
            try:
                photo = Image.open(photo_file)
                photos.append(photo)
                photos_processed.append(self.preprocess(photo))
                okay_files.append(photo_file)
            except Exception as e:
                print(f"Error loading image {photo_file}: {e}")
                continue

        # Preprocess all photos
        if len(photos_processed) == 0:
            return [], None

        photos_preprocessed = torch.stack(photos_processed).to(self.device)

        with torch.no_grad():
            # Encode the photos batch to compute the feature vectors and normalize them
            photos_features = self.model.encode_image(photos_preprocessed)
            # photos_features /= photos_features.norm(dim=-1, keepdim=True)

        return okay_files, photos_features.cpu().numpy()


if __name__ == "__main__":
    image_dir = "/mnt/ssd0/LifelogPicam/cathal"
    output_path = "/mnt/ssd0/embeddings"

    current_data = np.load("/home/allie/lifelog-picam/backend/features/cathal/conclip.features.npz", allow_pickle=True)
    existed = current_data["image_paths"].tolist()
    print("Found", len(existed), "existing photos:", existed[:5])
    existed_set = set(existed)

    # # another one
    # existed = pd.read_csv(f"{output_path}/photo_ids.csv")["photo_id"].tolist()
    # print("Found", len(existed), "existing photos:", existed[:5])
    # existed_set.update(existed)

    paths = []
    keys = []
    batch_size = 64

    EMBEDDING_MODEL = "conclip_vit_l14"
    images = glob.glob(f"{image_dir}/**/*.jpg", recursive=True)
    images = sorted(images)
    print("Found", len(images), "photos in total")
    for image in images:
        key = "/".join(image.split("/")[-2:])
        if key in existed_set:
            continue

        paths.append(image)
        keys.append(key)
    print("Found", len(paths), "photos")
    features_path = Path(output_path, EMBEDDING_MODEL)
    os.system(f"mkdir -p {features_path}")

    model = ConCLIPBinaryClassifier(
        model_path=checkpoint_path,
        device=device,
    )

    print("Computing features")
    batches = math.ceil(len(paths) / batch_size)
    for i in tqdm(range(batches)):
        batch_ids_path = features_path / f"{i:010d}.csv"
        batch_features_path = features_path / f"{i:010d}.npy"

        # Only do the processing if the batch wasn't processed yet
        if not batch_features_path.exists():
            try:
                # Select the photos for the current batch
                batch_files = paths[i * batch_size : (i + 1) * batch_size]

                # Compute the features and save to a numpy file
                valid_files, batch_features = model.compute_clip_features(
                    batch_files
                )
                if batch_features is None:
                    continue

                assert len(valid_files) == len(batch_features), f"Batch {i} failed {len(valid_files)} != {len(batch_features)}"

                np.save(batch_features_path, batch_features)
                # Save the photo IDs to a CSV file
                photo_ids = ["/".join(file.split("/")[-2:]) for file in valid_files]
                photo_ids_data = pd.DataFrame(photo_ids, columns=["photo_id"])
                photo_ids_data.to_csv(batch_ids_path, index=False)

            except Exception as e:
                # Catch problems with the processing to make the process more robust
                print(f"Problem with batch {i}")
                raise (e)

    features_list = [
        np.load(features_file) for features_file in sorted(features_path.glob("*.npy"))
    ]

    # Concatenate the features and store in a merged file
    features = np.concatenate(features_list)
    np.save(features_path / "features.npy", features)

    photo_ids = pd.concat(
        [pd.read_csv(ids_file) for ids_file in sorted(features_path.glob("*.csv"))]
    )
    photo_ids.to_csv(features_path / "photo_ids.csv", index=False)
    # os.system(f"rm {features_path}/0*")

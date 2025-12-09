import clip
from PIL import Image as PILImage
import numpy as np
import torch
from visual import SIGLIP, _split_text
from PIL import Image
from app_types import Array1D, Array2D

# the .pt file downloaded from the links above
device = "cuda"
checkpoint_path = "files/conclip_vit_l14.pt"

# the .pt file downloaded from the links above
device = "cpu"


def load_checkpoint(model, checkpoint_path):
    ckpt = torch.load(checkpoint_path, weights_only=False)
    model = model.float()
    model.load_state_dict(ckpt["model"])
    return model


class ConCLIPBinaryClassifier(SIGLIP):
    def __init__(self, model_path="conclip_vit_l14.pt", device="cuda"):
        self.device = device
        self.model, self.preprocess =clip.load("ViT-L/14", device=device)
        self.model = load_checkpoint(self.model, model_path)
        self.model = self.model.to(device)

    def predict(
        self, positive_query: str, negative_query: str, image_features: Array2D[np.float32]
    ):
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

    def encode_text(self, main_query: str, normalize=False) -> Array1D[np.float32]:
        sentences = _split_text(main_query, 77)
        tokens = clip.tokenize(sentences).to(device)
        with torch.no_grad():
            with torch.autocast(device):
                outputs = self.model.encode_text(tokens).mean(dim=0)
                if normalize:
                    outputs = outputs / outputs.norm(dim=-1, keepdim=True)
        return outputs.cpu().float().numpy()

    def encode_texts(self, texts: list[str], normalize=False) -> torch.Tensor:
        tokens = clip.tokenize(texts).to(device)
        with torch.no_grad():
            with torch.autocast(device):
                outputs = self.model.encode_text(tokens)
                if normalize:
                    outputs = outputs / outputs.norm(dim=-1, keepdim=True)
        return outputs.cpu().float()

    def encode_image(self, image_path: str) -> Array1D[np.float32]:
        image_read = PILImage.open(image_path).convert("RGB")
        inputs = self.preprocess(image_read).unsqueeze(0).to(device)
        with torch.no_grad():
            with torch.autocast(device):
                outputs = self.model.encode_image(inputs)
                outputs = outputs / outputs.norm(dim=-1, keepdim=True)
        return outputs.cpu().float().numpy()

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


conclip = ConCLIPBinaryClassifier(model_path=checkpoint_path, device=device)

import numpy as np
import torch
import webp
from PIL import Image as PILImage
from transformers.models.auto.modeling_auto import AutoModel
from transformers.models.auto.processing_auto import AutoProcessor
from app_types import Array1D

device = "cuda" if torch.cuda.is_available() else "cpu"

def _split_text(text: str, max_length: int):
    words = text.split()
    sentences = []
    current_sentence = ""

    for word in words:
        if len(current_sentence) + len(word) + 1 <= max_length:
            if current_sentence:
                current_sentence += " "
            current_sentence += word
        else:
            if current_sentence:
                sentences.append(current_sentence)
            current_sentence = word

    if current_sentence:
        sentences.append(current_sentence)

    return sentences


class SIGLIP:
    def __init__(self):
        self.name = "siglip"
        model = AutoModel.from_pretrained(
            "google/siglip-so400m-patch14-384",
            device_map=device,
            attn_implementation="sdpa",
            # quantization_config=bnb_config,
        )
        processor = AutoProcessor.from_pretrained(
            "google/siglip-so400m-patch14-384",
            device_map=device,
        )
        self.model = model
        self.processor = processor

        self.model.eval()
        self.model.to(device)

    def encode_text(self, main_query: str, normalize=False) -> Array1D[np.float32]:
        sentences = _split_text(main_query, 77)
        inputs = self.processor(
            text=sentences,
            return_tensors="pt",
            padding=True,
            truncation=True,
        )
        inputs.to(device)
        with torch.no_grad():
            with torch.autocast(device):
                outputs = self.model.get_text_features(**inputs).mean(dim=0)
                if normalize:
                    outputs = outputs / outputs.norm(dim=-1, keepdim=True)
        return outputs.cpu().float().numpy()

    def encode_image(self, image_path: str) -> Array1D[np.float32]:
        image_read = PILImage.open(image_path).convert("RGB")
        inputs = self.processor(
            images=image_read,
            return_tensors="pt",
            padding=True,
            truncation=True,
        )
        inputs.to(device)
        with torch.no_grad():
            with torch.autocast(device):
                outputs = self.model.get_image_features(**inputs)
                outputs = outputs / outputs.norm(dim=-1, keepdim=True)
        return outputs.cpu().float().numpy()


siglip_model = SIGLIP()




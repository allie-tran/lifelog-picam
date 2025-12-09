
import torch
import numpy as np
from typing import List
from visual import siglip_model

device = "cuda" if torch.cuda.is_available() else "cpu"

class ClipPromptClassifier:
    """
    Zero-shot classifier on top of CLIP features using text prompts.
    """
    def __init__(
        self,
        class_names: List[str],
        prompt_templates: List[str] | None = None,
    ):
        """
        Parameters
        ----------
        class_names : list of logical class names, e.g. ["social", "alone"]
        prompt_templates : list of templates like
            "a photo of {}",
            "a lifelog image of {}",
            ...
            If None: single template "a photo of {}".
        """
        self.class_names = class_names

        if prompt_templates is None:
            prompt_templates = ["a photo of {}"]
        self.prompt_templates = prompt_templates

        # Precompute text embeddings for prompts
        self.text_embs = self._build_text_embeddings()

    def _build_text_embeddings(self) -> torch.Tensor:
        """
        For each class, build multiple prompts and average their embeddings.
        Returns tensor of shape (num_classes, D).
        """
        all_class_embs = []
        with torch.no_grad():
            for cname in self.class_names:
                text_feat = siglip_model.encode_texts([template.format(cname) for template in self.prompt_templates], normalize=True)
                mean_feat = text_feat.mean(dim=0)
                mean_feat = mean_feat / mean_feat.norm()
                all_class_embs.append(mean_feat)

        text_embs = torch.stack(all_class_embs, dim=0)  # (C, D)
        return text_embs.to(device)

    def predict_proba_from_features(
        self, image_features: np.ndarray, temperature: float = 0.01
    ) -> np.ndarray:
        """
        image_features: shape (N, D) from the *same CLIP model*.
        Returns: probs shape (N, C)
        """
        # Ensure numpy -> torch and normalize
        img = torch.from_numpy(image_features).float().to(device)
        img = img / img.norm(dim=-1, keepdim=True)

        # cosine similarity is dot-product of L2-normalized
        logits = img @ self.text_embs.T  # (N, C)
        logits = logits / temperature    # temperature scaling

        # softmax for probabilities
        probs = torch.softmax(logits, dim=-1)
        return probs.detach().cpu().numpy()

    def predict_from_features(self, image_features: np.ndarray) -> List[str]:
        """
        Returns the most probable class for each feature vector.
        """
        probs = self.predict_proba_from_features(image_features)
        idx = probs.argmax(axis=-1)
        return [self.class_names[i] for i in idx]

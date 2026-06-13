from core.config import SEARCH_MODEL
from integrations.visual.siglip import siglip_model, SIGLIP
from integrations.visual.conclip import conclip_model
from integrations.visual.openai_vit14 import CLIPViT14

clip_model = siglip_model if SEARCH_MODEL == "siglip" else conclip_model

# device = "cuda"
# openai_clip_model = CLIPViT14(device=device)

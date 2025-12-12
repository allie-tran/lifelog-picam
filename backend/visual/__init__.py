from constants import SEARCH_MODEL
from visual.siglip import siglip_model
from visual.conclip import conclip_model

clip_model = siglip_model if SEARCH_MODEL == "siglip" else conclip_model


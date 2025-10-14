from typing import Literal
from mongodb_odm import Document
from dependencies import CamelCaseModel

class VideoSettings(CamelCaseModel):
    fps: int = 30
    max_duration: int = 60  # in seconds

class TimelapseSettings(CamelCaseModel):
    interval: int = 60  # in seconds

class PiCamControl(Document, CamelCaseModel):
    username: str

    capture_mode: Literal["photo", "video"] = "photo"
    video_settings: VideoSettings = VideoSettings()
    timelapse_settings: TimelapseSettings = TimelapseSettings()

    class ODMConfig(Document.ODMConfig):
        collection_name = "controls"


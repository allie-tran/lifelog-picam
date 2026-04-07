# Storing App Endpoints

from mongodb_odm import Document

class VideoSettings(Document):
    fps: int = 30
    max_duration: int = 60  # in seconds

class ImageSettings(Document):
    timelapse_interval: int = 5  # in seconds

class AppSettings(Document):
    """App Settings Document"""
    user_id: str

    capture_mode: Literal["video", "image"] = "image"
    video_settings: VideoSettings = VideoSettings()
    image_settings: ImageSettings = ImageSettings()

    class Collection:
        name = "settings"


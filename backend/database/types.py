from pydantic import BaseModel

class ObjectDetection(BaseModel):
    label: str
    confidence: float
    bbox: list[int]  # [x_min, y_min, x_max, y_max]

class ImageRecord(BaseModel):
    image_path: str # YYYY-MM-DD/YYMMDD_HHMMSS.jpg
    timestamp: str  # ISO 8601 format

    objects: list[ObjectDetection]
    people: list[ObjectDetection]

    activity: list[str]

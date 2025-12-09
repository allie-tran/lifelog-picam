from dependencies import CamelCaseModel
from typing import Optional

class InitUploadRequest(CamelCaseModel):
    device: str
    date_format: str  # Python strptime format, e.g. "%Y%m%d_%H%M%S"


class InitUploadResponse(CamelCaseModel):
    upload_id: str


class CompleteUploadRequest(CamelCaseModel):
    upload_id: str


class CompleteUploadResponse(CamelCaseModel):
    job_id: str


class ProcessingStatusResponse(CamelCaseModel):
    job_id: str
    status: str           # "pending", "processing", "done", "error"
    progress: float       # 0.0–1.0
    message: Optional[str]


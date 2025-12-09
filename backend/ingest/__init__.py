import uuid
from pathlib import Path
from typing import Dict
import json

from fastapi import FastAPI, UploadFile, File, Form, BackgroundTasks, HTTPException
from sessions.redis import RedisClient
from constants import DIR
from ingest.types import InitUploadRequest, InitUploadResponse, CompleteUploadRequest, CompleteUploadResponse, ProcessingStatusResponse
from ingest.utils import process_zip_job

app = FastAPI()
redis_client = RedisClient()

UPLOAD_DIR = Path(DIR)
UPLOAD_DIR.mkdir(exist_ok=True)


@app.post("/init", response_model=InitUploadResponse)
async def init_upload(req: InitUploadRequest):
    upload_id = str(uuid.uuid4())
    zip_path = UPLOAD_DIR / req.device / f"{upload_id}.zip.part"
    if not zip_path.parent.exists():
        zip_path.parent.mkdir(parents=True)

    data = {
        "device": req.device,
        "date_format": req.date_format,
        "zip_path": str(zip_path),
        "received_bytes": 0,
        "completed": False,
    }

    redis_client.set_json(f"upload:{upload_id}", data)

    # Ensure empty file
    with open(zip_path, "wb") as f:
        pass

    print(f"Initialized upload: {upload_id} for device: {req.device}")
    return InitUploadResponse(upload_id=upload_id)

@app.post("/chunk")
async def upload_chunk(
    upload_id: str = Form(...),
    chunk_index: int = Form(...),
    total_chunks: int = Form(...),
    chunk: UploadFile = File(...),
):
    print(f"Received chunk {chunk_index+1}/{total_chunks} for upload_id: {upload_id}")

    try:
        meta = redis_client.get_json(f"upload:{upload_id}")
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid upload_id")

    zip_path = Path(meta["zip_path"])

    # Append chunk bytes
    content = await chunk.read()
    with open(zip_path, "ab") as f:
        f.write(content)

    meta["received_bytes"] += len(content)

    return {"ok": True, "chunkIndex": chunk_index, "totalChunks": total_chunks}

@app.post("/complete", response_model=CompleteUploadResponse)
async def complete_upload(req: CompleteUploadRequest, background_tasks: BackgroundTasks):
    try:
        meta = redis_client.get_json(f"upload:{req.upload_id}")
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid upload_id")
    if meta.get("completed"):
        raise HTTPException(status_code=400, detail="Upload already completed")

    # Finalize file name (remove .part)
    tmp_path = Path(meta["zip_path"])
    final_zip_path = tmp_path.with_suffix(".zip")
    tmp_path.rename(final_zip_path)

    meta["completed"] = True
    meta["zip_path"] = str(final_zip_path)

    # Create processing job
    job_id = str(uuid.uuid4())
    data = {
        "status": "pending",
        "progress": 0.0,
        "message": None,
        "device": meta["device"],
        "date_format": meta["date_format"],
        "zip_path": str(final_zip_path),
    }
    redis_client.set_json(f"processing_job:{job_id}", data)

    # Start background processing
    background_tasks.add_task(process_zip_job, job_id, UPLOAD_DIR)

    return CompleteUploadResponse(job_id=job_id)

@app.get("/processing-status/{job_id}", response_model=ProcessingStatusResponse)
async def get_processing_status(job_id: str):
    job = redis_client.get_json(f"processing_job:{job_id}")
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")

    return ProcessingStatusResponse(
        job_id=job_id,
        status=job["status"],
        progress=float(job.get("progress", 0.0)),
        message=job.get("message"),
    )

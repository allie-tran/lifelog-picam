import zipfile
from datetime import datetime
from pathlib import Path

import requests
from constants import LOCAL_PORT
from sessions.redis import RedisClient

redis_client = RedisClient()


def process_zip_job(job_id: str, UPLOAD_DIR: Path):
    job = redis_client.get_json(f"processing_job:{job_id}")
    if not job:
        return

    max_percentage = 0.3
    job["status"] = "processing"
    zip_path = Path(job["zip_path"])
    device = job["device"]
    date_format = job["date_format"]

    try:
        with zipfile.ZipFile(zip_path, "r") as zf:
            # Filter to files only
            namelist = [n for n in zf.namelist() if not n.endswith("/")]
            total_files = len(namelist)
            all_files = []
            if total_files == 0:
                job["status"] = "done"
                job["progress"] = 1.0
                job["message"] = "No files found in zip."
                return

            for i, member in enumerate(namelist, start=1):
                new_filename = process_file(member, zf, device, date_format, UPLOAD_DIR)
                if new_filename:
                    all_files.append(new_filename)

                # Update progress
                if i % 5000 == 0 or i == total_files:
                    job["progress"] = i / total_files * max_percentage
                    job["all_files"] = all_files
                    job["message"] = f"Saved {i}/{total_files} files."
                    redis_client.set_json(f"processing_job:{job_id}", job)

        job["status"] = "done"
        job["message"] = f"Saved {total_files} files. Moving to processing."
        redis_client.set_json(f"processing_job:{job_id}", job)

        # Send a request to upadte app
        requests.post(f"http://localhost:{LOCAL_PORT}/update-app?job_id={job_id}")

    except Exception as e:
        job["status"] = "error"
        job["message"] = str(e)
        job["progress"] = 0.0
        redis_client.set_json(f"processing_job:{job_id}", job)

    # Delete the zip file to save space
    if zip_path.exists():
        zip_path.unlink()

    # Cleanup parts
    if zip_path.with_suffix(".part").exists():
        zip_path.with_suffix(".part").unlink()


def process_file(
    member: str, zf: zipfile.ZipFile, device: str, date_format: str, UPLOAD_DIR: Path
):
    with zf.open(member) as f:
        # Decide where to save each file
        # e.g., per device in uploads/device/YYYY-MM-DD/...
        out_dir = UPLOAD_DIR / device
        out_dir.mkdir(parents=True, exist_ok=True)

        # Keep original filename
        filename = Path(member).name

        # Parse timestamp from filename (without extension)
        stem = Path(filename).stem
        try:
            dt = datetime.strptime(stem, date_format)
        except ValueError as e:
            # Could log or mark as failed; for now, skip
            print(e)
            dt = None
            print(
                f"Failed to parse date from filename: {filename} with format {date_format}"
            )
            return None

        date = dt.strftime("%Y-%m-%d")
        new_filename = dt.strftime("%Y%m%d_%H%M%S") + Path(filename).suffix
        out_path = out_dir / date / new_filename
        if not out_path.parent.exists():
            out_path.parent.mkdir(parents=True, exist_ok=True)

        with open(out_path, "wb") as out_f:
            out_f.write(f.read())

        return f"{device}/{date}/{new_filename}"

import os
from datetime import datetime

import requests

BACKEND_URL = "https://dcu.allietran.com/omi/be"
UPLOAD_URL = "https://dcu.allietran.com/omi/be/upload-image"
CHECK_URL = "https://dcu.allietran.com/omi/be/check-image-uploaded"
CHECK_ALL_URL = "https://dcu.allietran.com/omi/be/check-all-images-uploaded"
OUTPUT = "Camera/timelapse"

def send_image(image_path, uploaded_files, LOG_FILE):
    if image_path in uploaded_files:
        return "photo"

    timestamp = datetime.strptime(
        os.path.basename(image_path).replace(".jpg", ""), "%Y%m%d_%H%M%S"
    )
    timestamp = int(timestamp.timestamp() * 1000)

    # Send form-data request
    with open(image_path, "rb") as img_file:
        files = {
            "file": (os.path.basename(image_path), img_file, "image/jpeg"),
            "timestamp": (None, str(timestamp)),
        }
        response = requests.put(UPLOAD_URL, files=files)

    if response.status_code == 200:
        print(f"Uploaded: {image_path}")
        uploaded_files.add(image_path)
        with open(LOG_FILE, "a") as log:
            log.write(f"{image_path}\n")
        return response.json()

    return "photo"

def send_video(video_path, uploaded_files, LOG_FILE):
    if video_path in uploaded_files:
        return "video"

    timestamp = datetime.strptime(
        os.path.basename(video_path).replace(".h264", ""), "%Y%m%d_%H%M%S"
    )
    timestamp = int(timestamp.timestamp() * 1000)

    # Send form-data request
    with open(video_path, "rb") as vid_file:
        files = {
            "file": (os.path.basename(video_path), vid_file, "video/h264"),
            "timestamp": (None, str(timestamp)),
        }
        response = requests.put(UPLOAD_URL, files=files)

    if response.status_code == 200:
        print(f"Uploaded: {video_path}")
        uploaded_files.add(video_path)
        with open(LOG_FILE, "a") as log:
            log.write(f"{video_path}\n")
        return response.json()

    return "video"


def check_if_connected():
    try:
        response = requests.get("https://www.google.com", timeout=5)
        return response.status_code == 200
    except requests.RequestException:
        return False

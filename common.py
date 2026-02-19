import os
from datetime import datetime

import requests
from dotenv import load_dotenv

import nacl.utils
from nacl.public import PrivateKey, Box, PublicKey


load_dotenv()

device_id = os.getenv("DEVICE_ID", "allie")
DEVICE_SECRET_KEY = os.getenv("DEVICE_SECRET_KEY", "")
SERVER_PUBLIC_KEY = os.getenv("SERVER_PUBLIC_KEY", "")
assert DEVICE_SECRET_KEY and SERVER_PUBLIC_KEY, "Both DEVICE_SECRET_KEY and SERVER_PUBLIC_KEY environment variables must be set."
box = Box(PrivateKey(bytes.fromhex(DEVICE_SECRET_KEY)), PublicKey(bytes.fromhex(SERVER_PUBLIC_KEY)))

BACKEND_URL = "https://dcu.allietran.com/selfhealth/be"
UPLOAD_URL = f"{BACKEND_URL}/upload-image"
UPLOAD_VIDEO_URL = f"{BACKEND_URL}/upload-video"
CHECK_URL = f"{BACKEND_URL}/check-image-uploaded"
CHECK_ALL_URL = f"{BACKEND_URL}/check-all-images-uploaded"
OUTPUT = "Camera/timelapse"

IMAGE_EXTENSION = ".jpg"

def send_image(image_path, uploaded_files, LOG_FILE):
    if image_path in uploaded_files:
        return "photo"

    timestamp = datetime.strptime(
        os.path.basename(image_path).replace(IMAGE_EXTENSION, ""), "%Y%m%d_%H%M%S"
    )
    timestamp = int(timestamp.timestamp() * 1000)

    # Send form-data request
    with open(image_path, "rb") as img_file:
        # the file is encrypted, so we don't need to encrypt it again. Just send it as is.
        files = {
            "file": (os.path.basename(image_path), img_file, f"image/jpeg"),
            "timestamp": (None, str(timestamp)),
        }
        response = requests.put(UPLOAD_URL, files=files, headers={"X-Device-ID": device_id})

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
            # "timestamp": (None, str(timestamp)),
        }
        response = requests.put(UPLOAD_VIDEO_URL, files=files, headers={"X-Device-ID": device_id})

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

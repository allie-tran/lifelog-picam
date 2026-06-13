import os
import json
import threading
import time
from datetime import datetime
from tzlocal import get_localzone

import requests
from dotenv import load_dotenv
from nacl.public import Box, PrivateKey, PublicKey

load_dotenv()
device_id = os.getenv("DEVICE_ID", "selfhealth")
DEVICE_SECRET_KEY = os.getenv("DEVICE_SECRET_KEY", "")
SERVER_PUBLIC_KEY = os.getenv("SERVER_PUBLIC_KEY", "")
assert (
    DEVICE_SECRET_KEY and SERVER_PUBLIC_KEY
), "Both DEVICE_SECRET_KEY and SERVER_PUBLIC_KEY environment variables must be set."
box = Box(
    PrivateKey(bytes.fromhex(DEVICE_SECRET_KEY)),
    PublicKey(bytes.fromhex(SERVER_PUBLIC_KEY)),
)

BACKEND_URL = "https://dcu.allietran.com/selfhealth/be"
# New
UPLOAD_URL = f"{BACKEND_URL}/images/upload-image"
CHECK_ALL_URL = f"{BACKEND_URL}/images/check-all-images-uploaded"
UPLOAD_GPS_URL = f"{BACKEND_URL}/location/upload-gps"

# Old
UPLOAD_VIDEO_URL = f"{BACKEND_URL}/upload-video"

OUTPUT = "Camera/timelapse"

IMAGE_EXTENSION = ".jpg"

# Shared HTTP session so uploads reuse one TCP + TLS connection instead of
# doing a fresh handshake every ~10s. Saves CPU, radio time and latency on the
# Pi Zero 2W. All backend calls (image/video/GPS/sync) go through this.
session = requests.Session()


# Sentinel outcomes for a failed upload. Distinct objects so callers can tell
# them apart from a successful (truthy) response body.
RETRY = object()    # server down / transient — keep the file and try again
DISCARD = object()  # server rejected the file — delete it, never re-upload


_UPLOAD_TIMEOUT = 30  # seconds — generous for slow Pi WiFi but not infinite


# Statuses that mean the file's *payload* is permanently unusable: the server
# cannot decode/decrypt it, so re-uploading will never succeed. Only these
# trigger deletion. NOTE: auth/config failures (401/403/404) are deliberately
# excluded — they affect every image and are usually transient (device not yet
# provisioned, key rotation, DB hiccup); discarding on those would wipe the
# whole backlog. When in doubt we keep the file.
_DISCARD_STATUSES = {400, 413, 415, 422}


def _failure_outcome(status_code):
    """Map an HTTP error status to a retry/discard decision.

    Default is RETRY (keep the file) so nothing is lost on transient or
    misclassified errors. Only a known bad-payload status causes DISCARD.
    """
    return DISCARD if status_code in _DISCARD_STATUSES else RETRY

def send_image(image_path, uploaded_files, LOG_FILE):
    if image_path in uploaded_files:
        return "photo"

    # Send form-data request
    with open(image_path, "rb") as img_file:
        files = {
            "file": (os.path.basename(image_path), img_file, f"image/jpeg"),
        }
        response = session.put(
            UPLOAD_URL,
            files=files,
            data={"rotation": -90, "device": device_id, "tz": str(get_localzone())},
            timeout=_UPLOAD_TIMEOUT,
        )

    if response.status_code == 200:
        print(f"Uploaded: {image_path}")
        uploaded_files.add(image_path)
        with open(LOG_FILE, "a") as log:
            log.write(f"{image_path}\n")
        return response.json()

    outcome = _failure_outcome(response.status_code)
    action = "retrying" if outcome is RETRY else "discarding"
    print(f"Failed to upload {image_path}: {response.status_code} - {response.text} ({action})")
    return outcome


def send_video(video_path, uploaded_files, LOG_FILE):
    if video_path in uploaded_files:
        return "video"

    timestamp = datetime.strptime(
        os.path.basename(video_path).replace(".h264", ""), "%Y%m%d_%H%M%S%z"
    )
    timestamp = int(timestamp.timestamp() * 1000)

    with open(video_path, "rb") as vid_file:
        files = {
            "file": (os.path.basename(video_path), vid_file, "video/h264"),
        }
        response = session.put(
            UPLOAD_VIDEO_URL,
            files=files,
            headers={"X-Device-ID": device_id},
            timeout=_UPLOAD_TIMEOUT,
        )

    if response.status_code == 200:
        print(f"Uploaded: {video_path}")
        uploaded_files.add(video_path)
        with open(LOG_FILE, "a") as log:
            log.write(f"{video_path}\n")
        return response.json()

    outcome = _failure_outcome(response.status_code)
    action = "retrying" if outcome is RETRY else "discarding"
    print(f"Failed to upload {video_path}: {response.status_code} - {response.text} ({action})")
    return outcome


def send_gps(gps_path):
    if not os.path.exists(gps_path):
        return None
    with open(gps_path, "r") as gps_file:
        data = gps_file.read().strip()

    timestamp, latitude, longitude, elevation = data.strip().split(",")
    if latitude:
        payload = {
            "timestamp": timestamp,
            "latitude": float(latitude),
            "longitude": float(longitude),
            "device_id": device_id,
            "elevation": float(elevation) if elevation != "None" else None,
        }
        response = session.put(UPLOAD_GPS_URL, json=payload, timeout=_UPLOAD_TIMEOUT)

        if response.status_code == 200:
            print(f"Uploaded GPS data: {payload}")
            return response.json()
        else:
            print(
                f"Failed to upload GPS data: {response.status_code} - {response.text}"
            )
            return None


def get_latest_gps():
    response = session.get(f"{BACKEND_URL}/location/latest-gps?device={device_id}", timeout=10)
    if response.status_code == 200:
        gps_data = response.json()
        return gps_data
    else:
        print(
            f"Failed to fetch latest GPS data: {response.status_code} - {response.text}"
        )
        return None


def _sync_timezone():
    """Fetch GPS from server and apply timezone correction. Safe to call from any thread."""
    try:
        gps_data = get_latest_gps()
        if gps_data:
            tz = gps_data.get("timezone", "UTC")
            os.environ["TZ"] = tz
            time.tzset()
            print(f"Timezone synced to: {time.tzname} ({tz})")
    except Exception as e:
        print(f"Timezone sync failed: {e}")


def start_timezone_sync(interval_seconds: int = 300):
    """Start a daemon thread that re-syncs timezone every interval_seconds."""
    def _loop():
        while True:
            _sync_timezone()
            time.sleep(interval_seconds)

    t = threading.Thread(target=_loop, daemon=True, name="tz-sync")
    t.start()
    return t

def load_gps():
    if os.path.exists("latest_gps.json"):
        with open("latest_gps.json") as f:
            return json.load(f)
    else:
        return {"timestamp": "", "latitude": "", "longitude": "", "elevation": "", "timezone": str(get_localzone())}

def save_gps(gps_data):
    with open("latest_gps.json", "w") as f:
        json.dump(gps_data, f)

_connectivity_cache: dict = {"ok": False, "ts": 0.0}
_CONNECTIVITY_CACHE_TTL = 30  # seconds

def check_if_connected() -> bool:
    now = time.monotonic()
    if now - _connectivity_cache["ts"] < _CONNECTIVITY_CACHE_TTL and _connectivity_cache["ok"]:
        return True
    try:
        response = requests.head("https://www.google.com", timeout=5)
        # Only 2xx/3xx mean we actually reached a working network; 4xx/5xx do not.
        ok = response.status_code < 400
    except Exception:
        ok = False
    _connectivity_cache["ok"] = ok
    _connectivity_cache["ts"] = now
    return ok

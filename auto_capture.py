import os
from datetime import datetime
# Wait for 5 minutes before checking again
import time

import requests

UPLOAD_URL = "https://dcu.allietran.com/omi/be/upload-image"
CHECK_URL = "https://dcu.allietran.com/omi/be/check-image-uploaded"
CHECK_ALL_URL = "https://dcu.allietran.com/omi/be/check-all-images-uploaded"

missing_files = set()
uploaded_files = set()


def send_image(image_path):
    if image_path in uploaded_files:
        return True

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
        response = requests.post(UPLOAD_URL, files=files)

    if response.status_code == 200:
        print(f"Uploaded: {image_path}")
        uploaded_files.add(image_path)
        with open(LOG_FILE, "a") as log:
            log.write(f"{image_path}\n")
        return True


def check_if_connected():
    try:
        response = requests.get("https://www.google.com", timeout=5)
        return response.status_code == 200
    except requests.RequestException:
        return False


def check_if_folder_is_synced(date: str):
    if os.path.exists(os.path.join(OUTPUT, date, ".synced")):
        print(f"Folder {date} is already synced.")
        return []

    files = set(
        os.path.join(OUTPUT, f) for f in os.listdir(OUTPUT) if f.endswith(".jpg")
    )
    files.difference_update(uploaded_files)

    if not files:
        print(f"All files in folder {date} are already uploaded.")
        # create "folder/.synced"
        with open(os.path.join(OUTPUT, date, ".synced"), "w") as f:
            f.write("All files are synced.\n")
        return []

    payload = {"date": date, "all_files": list(files)}
    try:
        response = requests.post(CHECK_ALL_URL, json=payload, timeout=10)
        if response.status_code == 200:
            data = response.json()
            synced_files = set(data.get("synced_files", []))
            missing = files - synced_files
            missing_files.update(missing)
            uploaded_files.update(synced_files)
            print(f"Folder {date}: {len(synced_files)} files synced, {len(missing)} files missing.")
            return list(missing)
    except requests.RequestException as e:
        print(f"Error checking folder sync status: {e}")

    print(f"Could not verify sync status for folder {date}. Assuming all files are missing.")
    return list(files)
# Try to sync files every 5 minutes if connected to the internet
if __name__ == "__main__":
    # Check all "synced_files.txt" in all subfolders
    OUTPUT = "Camera/timelapse"
    LOG_FILE = "synced_files.txt"
    for folder in os.listdir(OUTPUT):
        folder_path = os.path.join(OUTPUT, folder)
        if os.path.isdir(folder_path):
            log_path = os.path.join(folder_path, LOG_FILE)
            if os.path.exists(log_path):
                with open(log_path, "r") as log:
                    for line in log:
                        uploaded_files.add(line.strip())

    print(f"Loaded {len(uploaded_files)} uploaded files from logs.")
    while True:
        if check_if_connected():
            print("Connected to the internet. Checking for missing files...")
            for folder in os.listdir(OUTPUT):
                folder_path = os.path.join(OUTPUT, folder)
                if os.path.isdir(folder_path):
                    date_str = folder
                    missing = check_if_folder_is_synced(date_str)
                    for file in missing:
                        send_image(file)
        else:
            print("No internet connection. Retrying in 5 minutes.")
        time.sleep(300)

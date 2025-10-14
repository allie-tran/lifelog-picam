from common import CHECK_ALL_URL, OUTPUT, check_if_connected, send_image, send_video
import requests
from datetime import datetime
import os
import time

missing_files = set()
uploaded_files = set()

def check_if_folder_is_synced(date: str):
    DATE_DIR = os.path.join(OUTPUT, date)
    if os.path.exists(os.path.join(DATE_DIR, ".synced")):
        print(f"Folder {DATE_DIR} is already synced.")
        return []

    files = set(os.path.join(DATE_DIR, f) for f in os.listdir(DATE_DIR))
    files = set(f for f in files if f.endswith(".jpg") or f.endswith(".mp4"))
    files.difference_update(uploaded_files)

    if not files:
        print(f"All files in folder {date} are already uploaded.")
        with open(os.path.join(OUTPUT, date, ".synced"), "w") as f:
            f.write("All files are synced.\n")
        return []

    # Only get filenames
    basenames = set(os.path.basename(f) for f in files)
    payload = {"date": date, "all_files": list(basenames)}

    try:
        response = requests.post(CHECK_ALL_URL, json=payload, timeout=10)
        if response.status_code == 200:
            data = response.json()
            missing = set(data)
            missing = set(os.path.join(DATE_DIR, f) for f in missing)
            synced_files = files - missing
            missing_files.update(missing)
            uploaded_files.update(synced_files)
            print(
                f"Folder {date}: {len(synced_files)} files synced, {len(missing)} files missing."
            )
            if not missing:
                with open(os.path.join(OUTPUT, date, ".synced"), "w") as f:
                    f.write("All files are synced.\n")

            return list(missing)
    except requests.RequestException as e:
        print(f"Error checking folder sync status: {e}")


    print(
        f"Could not verify sync status for folder {date}. Assuming all files are missing."
    )
    return list(files)


def check_if_outdated(date: str, threshold_days: int = 7):
    DATE_DIR = os.path.join(OUTPUT, date)
    if not os.path.exists(DATE_DIR):
        return False

    folder_date = datetime.strptime(date, "%Y-%m-%d")
    age_days = (datetime.now() - folder_date).days
    return age_days > threshold_days


def cleanup(directory: str):
    # Remove the whole directory and its contents
    if os.path.exists(directory):
        print(f"Cleaning up directory: {directory}")
        os.system(f"rm -rf {directory}")


# Try to sync files every 5 minutes if connected to the internet
if __name__ == "__main__":
    # Check all "synced_files.txt" in all subfolders
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
        print("-" * 40)
        print("Current time:", datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
        if check_if_connected():
            print("Connected to the internet. Checking for missing files...")
            for folder in os.listdir(OUTPUT):
                folder_path = os.path.join(OUTPUT, folder)
                if os.path.isdir(folder_path):
                    date_str = folder
                    missing = check_if_folder_is_synced(date_str)
                    for file in missing:
                        if file.endswith(".mp4"):
                            send_video(file, uploaded_files, LOG_FILE)
                        elif file.endswith(".jpg"):
                            send_image(file, uploaded_files, LOG_FILE)

                    if not missing and check_if_outdated(date_str):
                        cleanup(folder_path)
        else:
            print("No internet connection. Retrying in 5 minutes.")
        time.sleep(300)

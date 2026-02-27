import traceback
from common import CHECK_ALL_URL, OUTPUT, check_if_connected, send_image, send_video, IMAGE_EXTENSION
import requests
from datetime import datetime
import os
import time

missing_files = set()
uploaded_files = set()

device_id = os.getenv("DEVICE_ID", "omi")

def check_if_folder_is_synced(date: str):
    DATE_DIR = os.path.join(OUTPUT, date)
    files = set(os.path.join(DATE_DIR, f) for f in os.listdir(DATE_DIR))
    files = set(f for f in files if f.endswith(IMAGE_EXTENSION) or f.endswith(".mp4"))
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
        response = requests.post(CHECK_ALL_URL, json=payload, timeout=10, headers={"X-Device-ID": device_id})
        if response.status_code == 200:
            missing, deleted = response.json()
            missing = set(missing)
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

            for f in deleted:
                deleted_file_path = os.path.join(DATE_DIR, f)
                if os.path.exists(deleted_file_path):
                    os.remove(deleted_file_path)
                    print(f"Deleted file {deleted_file_path} as per server instruction.")

            return sorted(missing)
        else:
            print(response.reason)
            print(response.json())


    except Exception as e:
        print(f"Error checking folder sync status: {e}")


    print(
        f"Could not verify sync status for folder {date}. Try again later."
    )
    return []


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
    print(f"Loaded {len(uploaded_files)} uploaded files from logs.")
    LOG_FILE = 'synced.txt'
    while True:
        print("-" * 40)
        print("Current time:", datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
        if check_if_connected():
            print("Connected to the internet. Checking for missing files...")
            all_folders = sorted(os.listdir(OUTPUT), reverse=True)
            print(all_folders)
            for folder in all_folders:
                folder_path = os.path.join(OUTPUT, folder)
                if os.path.isdir(folder_path):
                    date_str = folder
                    missing = check_if_folder_is_synced(date_str)
                    for file in missing:
                        if file.endswith(".mp4"):
                            send_video(file, uploaded_files, LOG_FILE)
                        elif file.endswith(IMAGE_EXTENSION):
                            send_image(file, uploaded_files, LOG_FILE)

                    if check_if_outdated(date_str):
                        cleanup(folder_path)
        else:
            print("No internet connection. Retrying in 1 minute.")
            time.sleep(60)

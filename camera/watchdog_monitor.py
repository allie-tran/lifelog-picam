import os
import time
from datetime import datetime
from queue import Queue

import requests
from watchdog.events import FileSystemEventHandler
from watchdog.observers import Observer

from common import (
    CHECK_ALL_URL,
    IMAGE_EXTENSION,
    OUTPUT,
    check_if_connected,
    send_gps,
    send_image,
    send_video,
)

# A queue to hold files that failed to upload
retry_stack = []
missing_files = set()
uploaded_files = set()
LOG_FILE = "synced.txt"

device_id = os.getenv("DEVICE_ID", "omi")


class NewFileHandler(FileSystemEventHandler):
    def on_created(self, event):
        """Called when a new file is created in the OUTPUT directory."""
        if event.is_directory:
            return
        # Wait for capture script to finish writing/encrypting
        time.sleep(2)
        self.add_file_to_stack(event.src_path)

    def add_file_to_stack(self, file_path):
        if file_path.endswith(".mp4") or file_path.endswith(IMAGE_EXTENSION):
            print(f"Adding to upload stack: {file_path}")
            retry_stack.append(file_path)


def process_stack():
    """Attempts to upload everything in the queue."""
    if len(retry_stack) == 0:
        return

    if not check_if_connected():  # From your common.py
        print("Still no internet. Skipping retry cycle.")
        return

    print(f"Attempting to upload {len(retry_stack)} items in the queue...")

    # Create a temporary list to hold items that fail again
    failed_again = []

    while len(retry_stack) > 0:
        file_path = retry_stack.pop() # Get the last item (LIFO)
        success = False
        try:
            if file_path.endswith(".mp4"):
                # Your existing send_video returns True/False based on success
                success = send_video(file_path, uploaded_files, LOG_FILE)
            elif file_path.endswith(IMAGE_EXTENSION):
                print(f"Attempting to upload image and GPS for {file_path}")
                send_gps(file_path.replace(IMAGE_EXTENSION, ".txt"))
                print(f"Uploading image {file_path}...")
                success = send_image(file_path, uploaded_files, LOG_FILE)
            else:
                print(f"Unsupported file type for {file_path}")
                continue
            if not success:
                failed_again.append(file_path)
        except Exception as e:
            print(f"Error uploading {file_path}: {e}")
            failed_again.append(file_path)

        # Micro-sleep to prevent Pi Zero CPU saturation
        time.sleep(0.5)

    # Put failed items back in the queue for the next retry cycle, maintaining LIFO order
    for item in failed_again[::-1]:
        retry_stack.append(item)


def check_if_folder_is_synced(date: str):
    DATE_DIR = os.path.join(OUTPUT, date)
    files = set(os.path.join(DATE_DIR, f) for f in os.listdir(DATE_DIR))
    files = set(f for f in files if f.endswith(IMAGE_EXTENSION) or f.endswith(".mp4"))
    files.difference_update(uploaded_files)

    # Only get filenames
    basenames = set(os.path.basename(f) for f in files)
    payload = {"date": date, "all_files": list(basenames), "device_id": device_id}

    try:
        now = datetime.now()
        print(
            f"Checking sync status for folder {date} at {now.strftime('%Y-%m-%d %H:%M:%S')}"
        )
        response = requests.post(
            CHECK_ALL_URL, json=payload, timeout=10
        )
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
            for f in deleted:
                deleted_file_path = os.path.join(DATE_DIR, f)
                if os.path.exists(deleted_file_path):
                    os.remove(deleted_file_path)
                    print(
                        f"Deleted file {deleted_file_path} as per server instruction."
                    )

            return sorted(missing)
        else:
            print(response.reason)
            print(response.json())

    except Exception as e:
        print(f"Error checking folder sync status: {e}")

    print(f"Could not verify sync status for folder {date}. Try again later.")
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


if __name__ == "__main__":
    # 1. Initial Sync: Add all missing files to the queue
    print("Initial startup sync...")
    all_folders = sorted(os.listdir(OUTPUT), reverse=True)
    for folder in all_folders:
        if check_if_outdated(folder):
            cleanup(os.path.join(OUTPUT, folder))
            continue
        missing = check_if_folder_is_synced(folder)
        for f in missing:
            retry_stack.append(f)

    # 2. Start Watchdog
    event_handler = NewFileHandler()
    observer = Observer()
    observer.schedule(event_handler, OUTPUT, recursive=True)
    observer.start()

    # 3. Responsive Main Loop
    try:
        while True:
            if len(retry_stack) > 0:
                if check_if_connected():
                    # Process the queue immediately if we have internet
                    process_stack()
                else:
                    print("No internet, waiting 1 minute before retrying...")
                    time.sleep(60)
            # This small sleep prevents the CPU from hitting 100%
            # while waiting for the Watchdog to put something in the queue
            time.sleep(1)
    except KeyboardInterrupt:
        observer.stop()
    observer.join()

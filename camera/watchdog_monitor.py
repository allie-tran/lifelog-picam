import os
import time
from datetime import datetime
from queue import Queue, Empty

import requests
from watchdog.events import FileSystemEventHandler
from watchdog.observers import Observer

from common import (
    CHECK_ALL_URL,
    IMAGE_EXTENSION,
    OUTPUT,
    check_if_connected,
    send_image,
    send_video,
    start_timezone_sync,
)

upload_queue: Queue = Queue()
uploaded_files: set = set()
LOG_FILE = "synced.txt"

device_id = os.getenv("DEVICE_ID", "omi")

_FILE_READY_TIMEOUT = 5   # seconds to wait for file to stop growing
_FILE_READY_POLL   = 0.25  # poll interval while waiting


def _wait_for_file_ready(file_path: str) -> bool:
    """Return True once the file exists and hasn't grown for one poll interval."""
    deadline = time.monotonic() + _FILE_READY_TIMEOUT
    prev_size = -1
    while time.monotonic() < deadline:
        try:
            size = os.path.getsize(file_path)
        except OSError:
            time.sleep(_FILE_READY_POLL)
            continue
        if size > 0 and size == prev_size:
            return True
        prev_size = size
        time.sleep(_FILE_READY_POLL)
    return False


class NewFileHandler(FileSystemEventHandler):
    def on_created(self, event):
        if event.is_directory:
            return
        path = event.src_path
        if not (path.endswith(".mp4") or path.endswith(IMAGE_EXTENSION)):
            return
        if _wait_for_file_ready(path):
            print(f"Queuing: {path}")
            upload_queue.put(path)
        else:
            print(f"File never became ready, skipping: {path}")


def process_queue():
    """Upload everything currently in the queue. Returns count of failures."""
    failed = []
    while True:
        try:
            file_path = upload_queue.get_nowait()
        except Empty:
            break
        try:
            if file_path.endswith(".mp4"):
                success = send_video(file_path, uploaded_files, LOG_FILE)
            elif file_path.endswith(IMAGE_EXTENSION):
                success = send_image(file_path, uploaded_files, LOG_FILE)
            else:
                continue
            if not success:
                failed.append(file_path)
        except Exception as e:
            print(f"Error uploading {file_path}: {e}")
            failed.append(file_path)

    for f in failed:
        upload_queue.put(f)

    return len(failed)


def check_if_folder_is_synced(date: str):
    DATE_DIR = os.path.join(OUTPUT, date)
    files = set(os.path.join(DATE_DIR, f) for f in os.listdir(DATE_DIR))
    files = set(f for f in files if f.endswith(IMAGE_EXTENSION) or f.endswith(".mp4"))
    files.difference_update(uploaded_files)

    basenames = set(os.path.basename(f) for f in files)
    payload = {"date": date, "all_files": list(basenames), "device_id": device_id}

    try:
        print(f"Checking sync status for folder {date} at {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        response = requests.post(CHECK_ALL_URL, json=payload, timeout=10)
        if response.status_code == 200:
            missing, deleted = response.json()
            missing = set(os.path.join(DATE_DIR, f) for f in missing)
            synced_files = files - missing
            uploaded_files.update(synced_files)
            print(f"Folder {date}: {len(synced_files)} synced, {len(missing)} missing.")
            for f in deleted:
                deleted_path = os.path.join(DATE_DIR, f)
                if os.path.exists(deleted_path):
                    os.remove(deleted_path)
                    print(f"Deleted {deleted_path} per server instruction.")
            return sorted(missing)
        else:
            print(response.reason)
    except Exception as e:
        print(f"Error checking folder sync status: {e}")

    print(f"Could not verify sync status for folder {date}. Try again later.")
    return []


def check_if_outdated(date: str, threshold_days: int = 7):
    DATE_DIR = os.path.join(OUTPUT, date)
    if not os.path.exists(DATE_DIR):
        return False
    folder_date = datetime.strptime(date, "%Y-%m-%d")
    return (datetime.now() - folder_date).days > threshold_days


def cleanup(directory: str):
    if os.path.exists(directory):
        print(f"Cleaning up: {directory}")
        os.system(f"rm -rf {directory}")


if __name__ == "__main__":
    # Sync timezone immediately then every 5 minutes in the background
    start_timezone_sync(interval_seconds=300)

    # 1. Initial sync — reconcile with server, queue missing files
    print("Initial startup sync...")
    all_folders = sorted(os.listdir(OUTPUT), reverse=True)
    for folder in all_folders:
        if check_if_outdated(folder):
            cleanup(os.path.join(OUTPUT, folder))
            continue
        for f in check_if_folder_is_synced(folder):
            upload_queue.put(f)

    print(f"Initial queue size: {upload_queue.qsize()}")

    # 2. Start watchdog
    event_handler = NewFileHandler()
    observer = Observer()
    observer.schedule(event_handler, OUTPUT, recursive=True)
    observer.start()

    # 3. Main loop — upload whenever there is work and connectivity
    backoff = 1
    try:
        while True:
            if not upload_queue.empty():
                if check_if_connected():
                    failures = process_queue()
                else:
                    print("No internet, waiting 60s...")
                    time.sleep(60)
            time.sleep(1)
    except KeyboardInterrupt:
        observer.stop()
    observer.join()

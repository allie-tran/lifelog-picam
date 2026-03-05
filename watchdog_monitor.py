import os
import time
from queue import Queue
from watchdog.observers import Observer
from watchdog.events import FileSystemEventHandler
from common import OUTPUT, send_image, send_video, IMAGE_EXTENSION, check_if_connected

# Assuming these are imported/available from your files
from monitor import check_if_folder_is_synced, uploaded_files, LOG_FILE

# A queue to hold files that failed to upload
retry_queue = Queue()


class NewFileHandler(FileSystemEventHandler):
    def on_created(self, event):
        if event.is_directory:
            return
        # Wait for capture script to finish writing/encrypting
        time.sleep(2)
        self.enqueue_file(event.src_path)

    def enqueue_file(self, file_path):
        if file_path.endswith(".mp4") or file_path.endswith(IMAGE_EXTENSION):
            print(f"Adding to queue: {file_path}")
            retry_queue.put(file_path)


def process_queue():
    """Attempts to upload everything in the queue."""
    if retry_queue.empty():
        return

    if not check_if_connected():  # From your common.py
        print("Still no internet. Skipping retry cycle.")
        return

    print(f"Attempting to upload {retry_queue.qsize()} files...")

    # Create a temporary list to hold items that fail again
    failed_again = []

    while not retry_queue.empty():
        file_path = retry_queue.get()
        success = False

        try:
            if file_path.endswith(".mp4"):
                # Your existing send_video returns True/False based on success
                success = send_video(file_path, uploaded_files, LOG_FILE)
            elif file_path.endswith(IMAGE_EXTENSION):
                success = send_image(file_path, uploaded_files, LOG_FILE)

            if not success:
                failed_again.append(file_path)
        except Exception as e:
            print(f"Error uploading {file_path}: {e}")
            failed_again.append(file_path)

        # Micro-sleep to prevent Pi Zero CPU saturation
        time.sleep(0.5)

    # Put failed items back in the queue for the next cycle
    for item in failed_again:
        retry_queue.put(item)


if __name__ == "__main__":
    # 1. Initial Sync: Add all missing files to the queue
    print("Initial startup sync...")
    all_folders = sorted(os.listdir(OUTPUT), reverse=True)
    for folder in all_folders:
        missing = check_if_folder_is_synced(folder)
        for f in missing:
            retry_queue.put(f)

    # 2. Start Watchdog
    event_handler = NewFileHandler()
    observer = Observer()
    observer.schedule(event_handler, OUTPUT, recursive=True)
    observer.start()

    # 3. Main Loop: Periodically process the queue
    try:
        while True:
            process_queue()
            # Wait 5 minutes between full retry attempts to save battery/CPU
            time.sleep(300)
    except KeyboardInterrupt:
        observer.stop()
    observer.join()

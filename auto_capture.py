import os
import queue
import signal
import subprocess
import threading
import time
from concurrent.futures import ThreadPoolExecutor, TimeoutError
from datetime import datetime

import requests

from common import BACKEND_URL, OUTPUT, check_if_connected, send_image, send_video


def _check_capturing_mode():
    mode = "photo"
    try:
        response = requests.get(BACKEND_URL + "/controls/settings")
        if response.status_code == 200:
            data = response.json()
            print("Fetched settings:", data)
            mode = data.get("captureMode", "photo")
            return mode
    except:
        pass
    return mode

def check_capturing_mode(timeout=5):
    with ThreadPoolExecutor() as executor:
        future = executor.submit(_check_capturing_mode)
    try:
        result = future.result(timeout=timeout)
        return result
    except TimeoutError:
        print("Timeout while checking capturing mode. Defaulting to 'photo'.")
    return "photo"


def check_if_camera_connected():
    status = os.system("rpicam-still -n --output status.jpg")
    return status == 0

def capture_image():
    file_name = datetime.now().strftime("%Y%m%d_%H%M%S") + ".jpg"
    DATE_DIR = os.path.join(OUTPUT, datetime.now().strftime("%Y-%m-%d"))

    if not os.path.exists(DATE_DIR):
        os.makedirs(DATE_DIR)

    status = os.system(
        f"rpicam-still -n --output {os.path.join(DATE_DIR, file_name)} >> rpicam.log 2>&1"
    )
    if status != 0:
        print("Failed to capture image.")
        return None

    print("Captured image:", file_name)
    return os.path.join(DATE_DIR, file_name)

def record_video_until_interrupt(grace_period=5.0):
    file_name = datetime.now().strftime("%Y%m%d_%H%M%S") + ".h264"
    DATE_DIR = os.path.join(OUTPUT, datetime.now().strftime("%Y-%m-%d"))

    if not os.path.exists(DATE_DIR):
        os.makedirs(DATE_DIR)

    video_path = os.path.join(DATE_DIR, file_name)

    cmd = [
        "rpicam-vid",
        "--output", video_path,
        "-t", "0"
        "-n",
    ]
    print("Starting video recording:", video_path)
    try:
        process = subprocess.Popen(cmd)
    except Exception as e:
        print("Failed to start video recording:", e)
        return None

    try:
        while True:
            if process.poll() is not None:
                print("Video recording process ended unexpectedly.")
                return None

            mode = check_capturing_mode(timeout=5)
            if mode != "video":
                print("Capturing mode changed. Stopping video recording.")
                try:
                    process.send_signal(signal.SIGINT)
                except Exception as e:
                    print("Failed to stop video recording:", e)

                waited = 0.0
                while process.poll() is None and waited < grace_period:
                    time.sleep(0.5)
                    waited += 0.5

                if process.poll() is None:
                    print("Grace period exceeded. Killing video recording process.")
                    try:
                        process.kill()
                    except Exception as e:
                        print("Failed to kill video recording process:", e)
                break

            time.sleep(1)
    finally:
        if process.poll() is None:
            try:
                process.terminate()
                process.wait(timeout=2)
            except Exception as e:
                process.kill()

    print("Recorded video:", video_path)
    if os.path.exists(video_path):
        return os.path.join(DATE_DIR, file_name)

    print("Video file not found after recording.")
    return None

def main():
    while not check_if_camera_connected():
        print("Camera not connected. Retrying in 10 seconds...")
        time.sleep(1)

    print("Camera connected.")

    CAPTURE_INTERVAL = 10  # seconds
    CHECK_MODE_INTERVAL = 1 # seconds

    mode = check_capturing_mode(timeout=5)
    print(f"Initial capturing mode: {mode}")
    last_capture_time = time.time()
    while True:
        try:
            current_time = time.time()
            print(datetime.now())
            print(int(current_time - last_capture_time), "seconds.")
            new_mode = check_capturing_mode(timeout=5)
            print("Checked. Mode:", mode)
            if new_mode != mode:
                print(f"Capturing mode changed from {mode} to {new_mode}")
                mode = new_mode
            if mode == "photo":
                if current_time - last_capture_time >= 10:
                    last_capture_time = current_time
                    image_path = capture_image()

            elif mode == "video":
                video_path = record_video_until_interrupt()

            print("waiting...")
            time.sleep(1)
        except KeyboardInterrupt:
            print("Exiting...")
            break
        except Exception as e:
            print(f"Error in main loop: {e}")
            time.sleep(1)

if __name__ == "__main__":
    main()

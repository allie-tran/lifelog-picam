import os
import signal
import subprocess
import time
from datetime import datetime

import cv2
from picamzero import Camera
from common import OUTPUT, box

cam = Camera()
# orginally 4056 x 3040
cam.still_size = (2028, 1520)

def check_if_camera_connected():
    try:
        cam.take_photo("test.jpg")
        return True
    except Exception as e:
        print(e)
        return False

def capture_image():
    file_name = datetime.now().strftime("%Y%m%d_%H%M%S") + ".jpg"
    DATE_DIR = os.path.join(OUTPUT, datetime.now().strftime("%Y-%m-%d"))

    if not os.path.exists(DATE_DIR):
        os.makedirs(DATE_DIR)

    image_path = os.path.join(DATE_DIR, file_name)

    try:
        array = cam.capture_array() # RGB
        # Convert to BGR for OpenCV
        frame = cv2.cvtColor(array, cv2.COLOR_RGB2BGR)
        # resize to 2028 x 1520
        frame = cv2.resize(frame, (2028, 1520), interpolation=cv2.INTER_AREA)
        # encode to webp in memory
        io_buf = cv2.imencode('.jpg', frame)[1].tobytes()

        encrypted = box.encrypt(io_buf)
        with open(image_path, "wb") as f:
            f.write(encrypted)
        print("Captured image:", file_name)

    except Exception as e:
        print("Failed to capture image:", e)
        return None

    return image_path

def main():
    while not check_if_camera_connected():
        print("Camera not connected. Retrying in 10 seconds...")
        time.sleep(1)

    print("Camera connected.")

    CAPTURE_INTERVAL = 10  # seconds
    # mode = check_capturing_mode(timeout=5)
    mode = "photo"
    print(f"Initial capturing mode: {mode}")
    while True:
        try:
            last_capture_time = time.time()
            capture_image()
            now = time.time()
            if now - last_capture_time < CAPTURE_INTERVAL:
                time.sleep(CAPTURE_INTERVAL - (now - last_capture_time))
        except KeyboardInterrupt:
            print("Exiting...")
            break
        except Exception as e:
            print(f"Error in main loop: {e}")
            time.sleep(5)
        time.sleep(1)

if __name__ == "__main__":
    main()

import asyncio
import os
import time
from datetime import datetime, timezone

import aioserial
import cv2
from picamzero import Camera

from common import OUTPUT, box, load_gps, save_gps

cam = Camera()
# orginally 4056 x 3040
# Capture smaller than the 2028x1520 sensor mode: at 1 image/10s the upload
# (not the optics) is the bottleneck on the Pi Zero 2W, so fewer pixels means
# faster encrypt/encode/upload and less SD/server storage. 1456x1088 keeps
# enough detail for face/object detection; CLIP/LLM downscale further anyway.
CAPTURE_SIZE = (1456, 1088)
JPEG_QUALITY = 80  # cv2 default is 95; 80 ~halves file size with little visible loss
cam.still_size = CAPTURE_SIZE

def check_if_camera_connected():
    try:
        cam.take_photo("test.jpg")
        return True
    except Exception as e:
        print(e)
        return False


# --- Configuration ---
SERIAL_PORT = "/dev/serial0"
BAUD_RATE = 9600
CAPTURE_INTERVAL = 10  # seconds

# Global dictionary holding the latest valid state.
# If no fix has happened yet, it will fallback gracefully to "Searching..."
def parse_nmea_degrees(nmea_value, direction):
    """Converts NMEA DDMM.MMMM to Decimal Degrees"""
    if not nmea_value:
        return ""
    try:
        float_val = float(nmea_value)
        degrees = int(float_val / 100)
        minutes = float_val - (degrees * 100)
        decimal_degrees = degrees + (minutes / 60.0)
        if direction in ["S", "W"]:
            decimal_degrees = -decimal_degrees
        return decimal_degrees
    except ValueError:
        return ""


# --- Async Task 1: Continuous GPS Monitor ---
async def gps_worker():
    global gps
    print("Starting background GPS worker...")

    try:
        # Open serial port asynchronously
        aioserial_instance = aioserial.AioSerial(
            port=SERIAL_PORT, baudrate=BAUD_RATE, timeout=0.1
        )
    except Exception as e:
        # Failure to open the serial port is fatal for this worker; bail out so the
        # supervising script can restart the process.
        print(f"GPS Worker fatal error (serial open): {e}")
        return

    while True:
        try:
            # Check if there is data to read natively without stalling the event loop
            if aioserial_instance.in_waiting > 0:
                # Read a line asynchronously
                raw_line = await aioserial_instance.readline_async()
                line = raw_line.decode("utf-8", errors="replace").strip()
                print("Debug GPS Line:", line)

                if line.startswith("$GPRMC"):
                    data = line.split(",")

                    # A valid $GPRMC with the fields we read needs at least 7 commas
                    # (index 6 for lon hemisphere); guard against truncated sentences.
                    if len(data) > 6 and data[2] == "A":  # 'A' = Valid Active Fix
                        lat = parse_nmea_degrees(data[3], data[4])
                        lon = parse_nmea_degrees(data[5], data[6])
                        elevation = float(data[9]) if len(data) > 9 and data[9] else 0.0

                        # Update the global object immediately
                        gps = {
                            "timestamp": datetime.now(timezone.utc)
                            .astimezone()
                            .isoformat(),
                            "latitude": lat,
                            "longitude": lon,
                            "elevation": elevation,
                        }
                        save_gps(gps)
        except Exception as e:
            # A single malformed line / transient read error must not kill the worker.
            print(f"GPS Worker read error (continuing): {e}")

        # Yield control to allow the image worker to run
        await asyncio.sleep(0.1)


# --- Async Task 2: Strict Camera Schedule ---
async def image_worker():
    global gps
    print("Starting background Image capture worker...")

    while True:
        # Capture an image immediately when the loop starts / hits interval
        file_name = (
            datetime.now(timezone.utc).astimezone().strftime("%Y%m%d_%H%M%S%z.jpg")
        )
        DATE_DIR = os.path.join(OUTPUT, datetime.now(timezone.utc).strftime("%Y-%m-%d"))

        if not os.path.exists(DATE_DIR):
            os.makedirs(DATE_DIR)

        image_path = os.path.join(DATE_DIR, file_name)

        try:
            # Capture logic (keeps your exact encoding steps)
            array = cam.capture_array()
            frame = cv2.cvtColor(array, cv2.COLOR_RGB2BGR)
            frame = cv2.resize(frame, CAPTURE_SIZE, interpolation=cv2.INTER_AREA)
            io_buf = cv2.imencode(
                ".jpg", frame, [int(cv2.IMWRITE_JPEG_QUALITY), JPEG_QUALITY]
            )[1].tobytes()

            encrypted = box.encrypt(io_buf)

            # Write the GPS sidecar first so the uploader never sees a .jpg without it.
            gps = load_gps()
            if gps["latitude"] and time.time() - datetime.fromisoformat(gps["timestamp"]).timestamp() < 60:
                # Snapshot the current values of LATEST_GPS.
                txt_path = image_path.replace(".jpg", ".txt")
                with open(txt_path, "w") as f:
                    f.write(
                        f"{gps['timestamp']},{gps['latitude']},{gps['longitude']},{gps['elevation']}"
                    )

            # Write the image atomically: the watchdog uploader watches for the final
            # path, so write to a temp file and rename to avoid uploading a partial file.
            tmp_path = image_path + ".tmp"
            with open(tmp_path, "wb") as f:
                f.write(encrypted)
            os.replace(tmp_path, image_path)

            print(f"Captured image & text: {file_name} | Lat: {gps['latitude']}")

        except Exception as e:
            print("Failed to capture image:", e)

        # Strictly wait 10 seconds before taking the next photo
        # Unlike time.sleep(), asyncio.sleep() lets the GPS continue processing lines!
        await asyncio.sleep(CAPTURE_INTERVAL)


# --- Core Async Loop Controller ---
async def main():
    while not check_if_camera_connected():
        print("Camera not connected. Retrying in 10 seconds...")
        await asyncio.sleep(10)

    print("Camera connected. Starting concurrent tasks...")

    # Run both workers simultaneously
    await asyncio.gather(
        gps_worker(),
        image_worker()
    )

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\nProgram stopped safely by user.")

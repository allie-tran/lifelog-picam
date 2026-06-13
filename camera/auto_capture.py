import asyncio
import glob
import os
import time
from datetime import datetime, timezone

import aioserial
import cv2
import pynmea2
from picamzero import Camera

from common import OUTPUT, box, load_gps, save_gps

cam = Camera()
# orginally 4056 x 3040
# Capture smaller than the 2028x1520 sensor mode: at 1 image/10s the upload
# (not the optics) is the bottleneck on the Pi Zero 2W, so fewer pixels means
# faster encrypt/encode/upload and less SD/server storage. 1280x960 keeps
# enough detail for face/object detection; CLIP/LLM downscale further anyway.
CAPTURE_SIZE = (1280, 960)
JPEG_QUALITY = 70  # cv2 default is 95; lower tames noisy/low-light scenes that
                   # otherwise blow JPEG size up to ~1MB
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

    # Altitude only appears in GGA sentences (RMC has none), so remember the last
    # good one and attach it to the next position fix.
    last_altitude = None

    while True:
        try:
            # Check if there is data to read natively without stalling the event loop
            if aioserial_instance.in_waiting > 0:
                # Read a line asynchronously
                raw_line = await aioserial_instance.readline_async()
                line = raw_line.decode("utf-8", errors="replace").strip()
                if not line.startswith("$"):
                    await asyncio.sleep(0.1)
                    continue

                try:
                    # pynmea2 is talker-agnostic: it parses $GPRMC, $GNRMC, $GLRMC,
                    # etc. (the old code only matched $GP* and missed multi-GNSS
                    # modules that emit $GN*), and validates the checksum.
                    msg = pynmea2.parse(line)
                except pynmea2.ParseError:
                    await asyncio.sleep(0.1)
                    continue

                stype = msg.sentence_type

                if stype == "GGA":
                    # gps_qual 0 = no fix; altitude is field-named, not guessed.
                    if getattr(msg, "gps_qual", 0) and msg.altitude is not None:
                        last_altitude = float(msg.altitude)

                elif stype == "RMC" and getattr(msg, "status", "V") == "A":
                    # 'A' = active/valid fix. .latitude/.longitude are already
                    # signed decimal degrees.
                    gps = {
                        "timestamp": datetime.now(timezone.utc)
                        .astimezone()
                        .isoformat(),
                        "latitude": msg.latitude,
                        "longitude": msg.longitude,
                        "elevation": last_altitude,
                    }
                    save_gps(gps)
                    print(
                        f"GPS fix: {msg.latitude:.6f},{msg.longitude:.6f} "
                        f"alt={last_altitude}"
                    )
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

        os.makedirs(DATE_DIR, exist_ok=True)

        image_path = os.path.join(DATE_DIR, file_name)

        try:
            # capture_array() already returns frames at CAPTURE_SIZE (still_size),
            # so no resize is needed — just RGB->BGR for cv2's JPEG encoder.
            array = cam.capture_array()
            frame = cv2.cvtColor(array, cv2.COLOR_RGB2BGR)
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


def cleanup_partial_files():
    """Remove orphaned *.tmp left by an interrupted atomic write so they don't
    accumulate on the SD card (the uploader ignores them by extension)."""
    for tmp in glob.glob(os.path.join(OUTPUT, "**", "*.tmp"), recursive=True):
        try:
            os.remove(tmp)
            print(f"Removed stale temp file: {tmp}")
        except OSError:
            pass


# --- Core Async Loop Controller ---
async def main():
    cleanup_partial_files()

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

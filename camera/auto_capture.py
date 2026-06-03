import asyncio
import os
import time
from datetime import datetime, timezone

import aioserial
import cv2
from picamzero import Camera

from common import OUTPUT, box, get_latest_gps

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


# --- Configuration ---
SERIAL_PORT = "/dev/serial0"
BAUD_RATE = 9600
CAPTURE_INTERVAL = 10  # seconds

# Global dictionary holding the latest valid state.
# If no fix has happened yet, it will fallback gracefully to "Searching..."
LATEST_GPS = {"timestamp": "", "latitude": "", "longitude": "", "elevation": ""}


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
    global LATEST_GPS
    print("Starting background GPS worker...")

    try:
        # Open serial port asynchronously
        aioserial_instance = aioserial.AioSerial(
            port=SERIAL_PORT, baudrate=BAUD_RATE, timeout=0.1
        )

        while True:
            # Check if there is data to read natively without stalling the event loop
            if aioserial_instance.in_waiting > 0:
                # Read a line asynchronously
                raw_line = await aioserial_instance.readline_async()
                line = raw_line.decode("utf-8", errors="replace").strip()
                print("Debug GPS Line:", line)

                if line.startswith("$GPRMC"):
                    data = line.split(",")

                    if len(data) > 2 and data[2] == "A":  # 'A' = Valid Active Fix
                        lat = parse_nmea_degrees(data[3], data[4])
                        lon = parse_nmea_degrees(data[5], data[6])
                        elevation = float(data[9]) if len(data) > 9 and data[9] else 0.0

                        # Update the global object immediately
                        LATEST_GPS = {
                            "timestamp": datetime.now(timezone.utc)
                            .astimezone()
                            .isoformat(),
                            "latitude": lat,
                            "longitude": lon,
                            "elevation": elevation,
                        }

            # Yield control to allow the image worker to run
            await asyncio.sleep(0.1)

    except Exception as e:
        print(f"GPS Worker Error: {e}")


# --- Async Task 2: Strict Camera Schedule ---
async def image_worker():
    global LATEST_GPS
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
            frame = cv2.resize(frame, (2028, 1520), interpolation=cv2.INTER_AREA)
            io_buf = cv2.imencode(".jpg", frame)[1].tobytes()

            encrypted = box.encrypt(io_buf)
            with open(image_path, "wb") as f:
                f.write(encrypted)

            if LATEST_GPS["latitude"]:
                # Snapshot the current values of LATEST_GPS.
                txt_path = image_path.replace(".jpg", ".txt")
                with open(txt_path, "w") as f:
                    f.write(
                        f"{LATEST_GPS['timestamp']},{LATEST_GPS['latitude']},{LATEST_GPS['longitude']},{LATEST_GPS['elevation']}"
                    )

            print(f"Captured image & text: {file_name} | Lat: {LATEST_GPS['latitude']}")

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

    # Check latest GPS
    gps_data = get_latest_gps()
    print(
        f"Initial GPS Data: Timestamp: {gps_data['timestamp']}, Lat: {gps_data['latitude']}, Lon: {gps_data['longitude']}, Elevation: {gps_data['elevation']}"
    )
    os.environ['TZ'] = gps_data.get('timezone', 'UTC')  # Set timezone from GPS data if available
    time.tzset()  # Apply the timezone change
    print(f"System timezone set to: {time.tzname}")
    LATEST_GPS.update(gps_data)  # Update the global state with the initial GPS data

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

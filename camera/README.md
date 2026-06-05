# Setting up new Pi

Zuständig: Allie Tran
Fälligkeitsdatum: 4. Juni 2026
Prio: High
Projekt: SelfHealth (https://app.notion.com/p/SelfHealth-37373edd097e80589283d8a463db4edd?pvs=21)
Unternehmen: https://app.notion.com/37373edd097e80d687aed14f4c46e1df
Status: Nicht gestartet

# Raspberry Pi Zero 2W

## Flash image

- Download Raspberry Pi Imager
- Choose Raspberry Pi Zero 2W
- Operating System: Raspberry Pi OS Lite (64-bit)
- Setting up WLAN credentials

## Enable SSH (optional)

Use the main computer to SSH into pi for ease of copying and pasting.

Ensure it is connected to the WiFi.

Enable SSH

```bash
sudo raspi-config
```

Choose **Interface Options** > **SSH** > Enable

Find IP: 

```bash
ip address
```

Look under `wlan0` , it should look something like `inet 10.83.163.64/24`. Here the IP would be `10.83.163.64`. Then finally:

```bash
ssh username@10.83.163.64
```

## **Install the necessary packages**

```bash
sudo apt update
sudo apt upgrade
sudo apt install git
sudo apt install python3-pip
```

**In `/boot/firmware/config.txt`:**

```yaml
# Disable Bluetooth
dtoverlay=disable-bt

# Disable onboard audio
dtparam=audio=off

# Reduce GPU memory
gpu_mem=128

# Reduce CPU speed
arm_freq=600       # Default is 1000MHz
over_voltage=-2    # Lower voltage accordingly
```

**Disable Systemd Services**

```bash
# Disable Bluetooth service
sudo systemctl disable bluetooth hciuart

# Disable triggerhappy (hotkey daemon, rarely needed)
sudo systemctl disable triggerhappy

# Disable avahi (mDNS/Bonjour, if not needed)
sudo systemctl disable avahi-daemon

# Disable ModemManager (no modem = no need)
sudo systemctl disable ModemManager

# Disable logging (saves SD writes + CPU)
sudo systemctl disable systemd-journald
```

## Setting up the camera

```bash
wget -O install_pivariety_pkgs.sh \
  https://github.com/ArduCAM/Arducam-Pivariety-V4L2-Driver/releases/download/install_script/install_pivariety_pkgs.sh

chmod +x install_pivariety_pkgs.sh

# Install the kernel driver
./install_pivariety_pkgs.sh -p imx519

# Install Arducam's libcamera
./install_pivariety_pkgs.sh -p libcamera_dev
./install_pivariety_pkgs.sh -p libcamera_apps
```

**In `/boot/firmware/config.txt`:**

```bash
# Enable Camera
# dtoverlay=ov5647 # zerocam
dtoverlay=imx708 # camera module 3
# dtoverlay=imx519 # arducam 
# dtoverlay=imx500 # AI camera
```

![image.png](Setting%20up%20new%20Pi/image.png)

Test if the camera works

```bash
rpicam-still --output test.jpg
dmesg | grep -E "imx|arducam|csi|camera"
```

If `ERROR: rpicam-apps currently only supports the Raspberry Pi platforms` , try finding in **`/boot/firmware/config.txt:`**

```bash
camera_auto_detect=1
```

## Setting up Selfhealth code

Clone the repo: [https://github.com/allie-tran/lifelog-picam](https://github.com/allie-tran/lifelog-picam.git)

```jsx
git clone https://github.com/allie-tran/lifelog-picam.git
cd lifelog-picam
pip install -r requirements.txt --break-system-packages
```

Install packages from `requirements.txt`

Setting up `.env` file by running `python setup.py` . Then put the public key of the server in the same `.env` file. It should look something like this:

```jsx
DEVICE_ID=<A unique ID>
DEVICE_SECRET_KEY=a7a3918ea2260377f10081b53822a87b00cbd658c541f43c33438cbbf334b822
DEVICE_PUBLIC_KEY=f967fe42648f83f2c7eee0491fe8ea8fa9383e02e4446c5ca78cf7ec7943d968

SERVER_PUBLIC_KEY=e5172dae711f65f796f33c005a55c33698147190fbd0aba19962c5891a7b2a2f
```

Use the device’s public key to set up with the frontend.

### Test scripts

Send a dummy GPS first (TODO!)

```bash
curl -X PUT "http://your-backend/location/upload-gps" \
  -H "Content-Type: application/json" \
  -d '{"latitude": 53.3, "longitude": -6.2, "elevation": 10, "timestamp": "2025-11-23T12:00:00", "deviceId": "abc123"}'
```

```bash
cd camera
python auto_capture.py # Should capture a few images
python watchdog_monitor.py # Upload to the server
```

## Automate scripts

Setting up `crontab` : `crontab -e`

```bash
@reboot lifelog-picam/update_code.sh &
@reboot lifelog-picam/camera/auto_capture.sh &
@reboot lifelog-picam/camera/monitor.sh &

0 * * * * tail -n 2000 lifelog-picam/camera/monitor.log > lifelog-picam/camera/monitor.log
0 * * * * tail -n 2000 lifelog-picam/camera/auto_capture.log > lifelog-picam/camera/auto_capture.log
0 * * * * tail -n 2000 lifelog-picam/camera/rpicam.log > lifelog-picam/camera/rpicam.log
```
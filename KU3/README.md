# KC002 body camera (KU3)

The vendor-supplied KC002 body camera ([Alibaba listing](https://www.alibaba.com/product-detail/Compact-Camera-KC002-Dual-Display-1080P_1601912487114.html)), customised to take a still on an interval and buffer it on the SD card. The SelfHealth Android app (`mentra/selfhealth`) pulls the photos over FTP, uploads them to the backend, and configures the camera.

| File | What it is |
|---|---|
| `capture_loop.sh` | Runs on the camera (from the SD card). Takes the photos; reads its settings from the app. |
| `boot_hook.sh` | The block appended to the camera's `app_init.sh` so the loop starts on every boot. |
| `setup.py` | Sets up a new camera, or updates one, from a laptop. |

## Setting up a camera

```sh
# New camera: on the same Wi-Fi as the laptop. Installs the script and the boot hook, starts the loop.
python3 KU3/setup.py --host 192.168.1.71

# Updating the script only: SD card mounted on the laptop. (The boot hook is on the camera's flash,
# so this alone is enough only for a camera that has been set up with --host before.)
python3 KU3/setup.py --sd /media/$USER/<card>
```

`--host` asks before it modifies the camera's flash (`--yes` skips the question). Run it again at any time: it detects a hook that is already there and only refreshes and restarts the script.

Then in the app, go to **Device → Cameras → KC002**: set the IP (or tap **Find camera**), give the camera its own device id (for example `kc002_camera_2`; two cameras must never share one), register it, and turn sync on.

## How the app controls the camera

`capture_loop.sh` and the app share three files in `/tmp/sd/kc002_photos`, which is `/kc002_photos` over FTP. All three start with `_` and none ends in `.jpg`, so the app never mistakes them for photos.

| File | Written by | Contents |
|---|---|---|
| `_capture.conf` | app | `INTERVAL`, `PAUSED`, `RETENTION_HOURS`, `MIN_FREE_MB`, `QUIET_START`/`QUIET_END` (local hours), `UTC_OFFSET_MIN`, `PRUNE_RECORD`, `CONFIG_ID` |
| `_status.txt` | camera | `SCRIPT_VERSION`, `CONFIG_ID` (the last one it loaded), `STATE` (`capturing`/`paused`/`quiet`/`error`), `LAST_CAPTURE`, `LAST_ERROR`, `PHOTOS`, `FREE_MB`, `BATTERY`, … |
| `_snap_now` | app | Empty. The camera takes one photo and deletes the file. |

The script checks the config once a second and applies changes straight away. It never `source`s the file (it comes over the network, and the loop runs as root): it reads only the keys listed and checks each against a range. The app compares the camera's `CONFIG_ID` with its own and pushes again if they differ, so a change made while the camera is offline arrives with the next sync.

Other changes from v1:
- **No stale frames.** v1 copied `/tmp/jpg/1_jpgSnap.jpg` whether or not the trigger worked, so a failed trigger saved the previous frame again. v2 copies the frame only if it is newer than the trigger and its size has stopped changing.
- **No half-written photos over FTP.** Each photo is written as `.part` and then renamed.
- **No drift.** Each capture is scheduled from the planned time, not from when the last one finished.
- **Safer cleanup.** Cleanup runs every 5 minutes, not every frame. `RETENTION_HOURS=0` keeps photos until the card is low on space. The firmware's duplicate copies in `Record/Jpg` (about 250 MB a day) expire on the same retention (`PRUNE_RECORD=1`, the default). Below `MIN_FREE_MB`, those copies are deleted first, then the oldest photos.
- **Bounded log.** `umsinicmd`'s `OK` lines no longer fill `capture_loop.log`. Events go to `kc002_capture.log`, which is rotated at 256 KB.
- **One instance.** A pid file stops a second copy of the loop from starting.

## Camera facts

### Credentials

- **Shell (telnet): `root` / `body_cam5`.** The vendor's boot script sets this again on every boot (`echo "root:body_cam5" | chpasswd -m` in `app_init.sh`), so a changed password never lasts past a reboot. The credential in the vendor's firmware README has never worked.
- **FTP: `root` / `root`, or `root` / `body_cam5`.** BusyBox `ftpd` does not use the shell's password database. The vendor's init already starts it with write access to the SD card: `tcpsvd -vE 0.0.0.0 21 ftpd -w /tmp/sd`.
- **Web UI** (`http://<ip>`, user `admin`) is a separate account. If you lose it, use **Forget password** on the login page.

### What persists across a reboot

`/` is a RAM `rootfs` that is rebuilt on every boot, so edits to `/etc/init.d/rcS`, `/root` or `/mnt` are lost. Only two places persist:

- `/config` (`/dev/mtdblock4`, YAFFS2 on NAND, ~48 MB free). The vendor's application files live here.
- `/tmp/sd` (`/dev/mmcblk0`, exFAT). This is the real SD card, despite the `/tmp` path.

The boot chain is `/etc/init.d/rcS` → `/tmp/app/bin/app_init.sh`. `/tmp/app` is a symlink to `/config/app`. **On a fresh camera, `/config/app/bin/app_init.sh` is itself a symlink to the read-only `/system/app/bin/app_init.sh`.** The fix is to replace that one symlink with a real copy of the file, keeping a backup at `/tmp/sd/app_init.sh.orig`, and append `boot_hook.sh` to the copy. `setup.py` does both. The hook waits up to 30 s for the SD card to mount before it starts the loop. An earlier fixed `sleep 3` was sometimes too short, and the loop silently never started.

Anything custom must live on `/tmp/sd` or `/config`. An early version wrote photos to `/mnt/sdcard`, which is on the RAM rootfs, so they disappeared on every reboot.

### Vendor control API

`umsinicmd SysCtrl.<key>=<value>` on the device. The same command can also be sent as a UDP message `BC+UMSINI=SysCtrl.<key>=<value>` to `127.0.0.1:65500`. It is documented in the vendor's `apidemo/readme.txt`, and its implementation is in `apidemo/src/ctrl_msg.c`. Commands in use:

- `SysCtrl.Jpeg=1`: take a snapshot. It always goes to `/tmp/jpg/1_jpgSnap.jpg`, overwriting the previous one. The firmware also files its own copy under `Record/Jpg/<yyyymmdd_hh>/`.
- `BatteryInfo.Percent=?`: battery percentage, reported in `_status.txt`.
- `GpsInfo.gprmcbuf=?`: raw GPRMC. It returned empty in testing. The manual shows a SIM slot and GPS/4G icons, so re-test with a SIM inserted and outdoors before concluding the unit has no GPS.

Hardware: Ingenic T41ZX/T41ZN (MIPS), uClibc, BusyBox. The vendor bundle includes a `mips-gcc720-uclibc` cross toolchain for building anything custom.

### Why a phone is in the loop

The camera cannot upload to `dcu.allietran.com` directly, for two reasons:
- **TLS.** BusyBox's `ssl_client` supports only RSA cipher suites, and the backend's Let's Encrypt certificate is ECDSA, so the handshake fails with `alert code 40`. Fixes: reissue the certificate as RSA (`certbot --key-type rsa`), or put an RSA-terminated relay in front of the backend.
- **No upload client.** BusyBox `wget` has no `--post-data`/`--post-file`, and there is no `curl`. A direct upload would need a cross-compiled client.

Until one of those is solved, the camera buffers photos and the phone pulls them over FTP and uploads them, along with its own GPS.

### Registering a camera with the backend

Each camera needs its own device id, registered as a `camera` sensor. The app's Device tab does this (**Account & registration**). The same thing by hand:

```sh
TOKEN=$(curl -s -X POST https://dcu.allietran.com/selfhealth/be/auth/login \
  -H "Content-Type: application/json" \
  -d '{"username": "<user>", "password": "<pass>"}' | python3 -c 'import sys,json; print(json.load(sys.stdin)["token"])')

curl -s -X PUT https://dcu.allietran.com/selfhealth/be/auth/add-sensor \
  -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" \
  -d '{"deviceId": "kc002_camera_2", "deviceNickname": "KC002 Camera 2",
       "sensorType": "camera", "associatedUsername": "<user>"}'
```

### Open questions

- Does our unit have a populated SIM slot? If it does, does `GpsInfo.gprmcbuf=?` report a fix once 4G is up?
- After a Client → AP → Client Wi-Fi mode switch, the camera forgets its client credentials. The state is probably in `/config/app/conf`.

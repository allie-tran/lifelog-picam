#!/usr/bin/env python3
"""Set up a KC002 body camera for lifelogging, or update one already set up.

Two ways in, usable together:

  --sd /media/<you>/<card>   Camera's SD card mounted on this machine: copy the capture script
                             and create the photo folder. Works offline.
  --host <camera-ip>         Camera on the network: upload the script over FTP, install the boot
                             hook in /config/app/bin/app_init.sh over telnet, restart the loop,
                             and read back its status.

The SD card alone is enough to *update* a camera that already has the boot hook. A new camera needs
--host once, since the hook lives on the camera's flash, not the card.

Everything is idempotent: re-running on a set-up camera just refreshes the script and restarts it.
The flash is only touched after you confirm (or pass --yes). See README.md for the why of each step.
"""

import argparse
import ftplib
import io
import re
import shutil
import socket
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
SCRIPT = HERE / "capture_loop.sh"
BOOT_HOOK = HERE / "boot_hook.sh"
HOOK_MARKER = "custom: start KC002 photo capture loop"
APP_INIT = "/config/app/bin/app_init.sh"

# The shell password is re-applied by the vendor's init on every boot. FTP has been seen to take
# either, so both are tried.
TELNET_USER, TELNET_PASS = "root", "body_cam5"
FTP_CREDENTIALS = [("root", "body_cam5"), ("root", "root")]


# ---------------------------------------------------------------------------------------------
# SD card
# ---------------------------------------------------------------------------------------------

def setup_sd(card: Path) -> None:
    if not card.is_dir():
        sys.exit(f"{card} is not a directory — is the SD card mounted?")
    target = card / "capture_loop.sh"
    if target.exists():
        backup = card / "capture_loop.sh.bak"
        shutil.copyfile(target, backup)
        print(f"  backed up existing script to {backup.name}")
    # Via a temp name: a camera booting off this card must never see half a script.
    temp = card / "capture_loop.sh.new"
    shutil.copyfile(SCRIPT, temp)
    temp.replace(target)
    (card / "kc002_photos").mkdir(exist_ok=True)
    shutil.copyfile(BOOT_HOOK, card / "kc002_boot_hook.sh")
    print(f"  {target} installed, kc002_photos/ ready")


# ---------------------------------------------------------------------------------------------
# FTP
# ---------------------------------------------------------------------------------------------

def ftp_connect(host: str) -> ftplib.FTP:
    last_error = None
    for user, password in FTP_CREDENTIALS:
        try:
            ftp = ftplib.FTP(host, timeout=10)
            ftp.login(user, password)
            print(f"  FTP login ok as {user}/{password}")
            return ftp
        except ftplib.all_errors as error:
            last_error = error
    sys.exit(f"FTP login to {host} failed: {last_error}")


def ftp_upload(ftp: ftplib.FTP, name: str, data: bytes) -> None:
    # Upload under a temp name and rename. Overwriting a file a shell is executing in place makes
    # it read garbage mid-loop; a rename gives the new content a fresh inode instead.
    ftp.storbinary(f"STOR {name}.new", io.BytesIO(data))
    ftp.rename(f"{name}.new", name)


def ftp_read(ftp: ftplib.FTP, path: str) -> str | None:
    buffer = io.BytesIO()
    try:
        ftp.retrbinary(f"RETR {path}", buffer.write)
    except ftplib.error_perm:
        return None
    return buffer.getvalue().decode("utf-8", "replace")


# ---------------------------------------------------------------------------------------------
# Telnet — a minimal client, since telnetlib is gone from Python 3.13.
# ---------------------------------------------------------------------------------------------

IAC, DONT, DO, WONT, WILL, SB, SE = 255, 254, 253, 252, 251, 250, 240


class Telnet:
    def __init__(self, host: str, port: int = 23, timeout: float = 10):
        self.sock = socket.create_connection((host, port), timeout=timeout)
        self.buffer = b""
        self.counter = 0

    def _recv(self) -> None:
        chunk = self.sock.recv(4096)
        if not chunk:
            raise ConnectionError("camera closed the telnet session")
        out = bytearray()
        i = 0
        while i < len(chunk):
            byte = chunk[i]
            if byte != IAC:
                out.append(byte)
                i += 1
                continue
            if i + 1 >= len(chunk):
                break
            command = chunk[i + 1]
            if command in (DO, DONT, WILL, WONT) and i + 2 < len(chunk):
                option = chunk[i + 2]
                # Refuse every option: plain line mode is all a shell needs.
                if command == DO:
                    self.sock.sendall(bytes([IAC, WONT, option]))
                elif command == WILL:
                    self.sock.sendall(bytes([IAC, DONT, option]))
                i += 3
            elif command == SB:
                end = chunk.find(bytes([IAC, SE]), i)
                i = len(chunk) if end < 0 else end + 2
            else:
                i += 2
        self.buffer += bytes(out)

    def read_until(self, pattern: bytes, timeout: float = 15) -> re.Match:
        deadline = time.time() + timeout
        regex = re.compile(pattern)
        while True:
            match = regex.search(self.buffer)
            if match:
                self.buffer = self.buffer[match.end():]
                return match
            if time.time() > deadline:
                raise TimeoutError(f"no {pattern!r} from camera; got {self.buffer[-200:]!r}")
            self._recv()

    def send(self, line: str) -> None:
        self.sock.sendall(line.encode() + b"\r\n")

    def login(self, user: str, password: str) -> None:
        self.read_until(rb"login: ?")
        self.send(user)
        self.read_until(rb"[Pp]assword: ?")
        self.send(password)
        self.read_until(rb"[#$] ?$|[#$] ", timeout=10)

    def run(self, command: str, timeout: float = 30) -> tuple[int, str]:
        """Runs one command; returns (exit status, output). Framed by unique markers so the
        terminal's echo of the command line cannot be mistaken for its output."""
        self.counter += 1
        begin, end = f"__B{self.counter}__", f"__E{self.counter}__"
        self.send(f"echo {begin}; {command}; echo {end} $?")
        self.read_until(re.escape(begin).encode() + rb"\r?\n", timeout)
        match = self.read_until(rb"(?s)(.*?)" + re.escape(end).encode() + rb" (\d+)", timeout)
        return int(match.group(2)), match.group(1).decode("utf-8", "replace").strip()

    def close(self) -> None:
        try:
            self.send("exit")
        finally:
            self.sock.close()


def confirm(question: str, assume_yes: bool) -> bool:
    if assume_yes:
        return True
    return input(f"{question} [y/N] ").strip().lower() in ("y", "yes")


def setup_host(host: str, assume_yes: bool, skip_upload: bool) -> None:
    ftp = ftp_connect(host)
    if not skip_upload:
        ftp_upload(ftp, "capture_loop.sh", SCRIPT.read_bytes())
        ftp_upload(ftp, "kc002_boot_hook.sh", BOOT_HOOK.read_bytes())
        print("  capture_loop.sh and kc002_boot_hook.sh uploaded to the SD card")
    ftp.quit()

    print(f"  telnet {host} …")
    tn = Telnet(host)
    tn.login(TELNET_USER, TELNET_PASS)

    _, listing = tn.run(f"ls -la {APP_INIT}")
    is_symlink = "->" in listing
    hooked = tn.run(f"grep -q '{HOOK_MARKER}' {APP_INIT}")[0] == 0

    if hooked:
        print("  boot hook already installed")
    else:
        print(f"\n  {APP_INIT}:\n    {listing}")
        steps = []
        if is_symlink:
            steps.append("replace the symlink to read-only /system with a writable copy "
                         "(vendor original backed up to /tmp/sd/app_init.sh.orig)")
        steps.append("append the capture-loop boot hook to it")
        print("  About to modify the camera's flash:\n" + "".join(f"    - {s}\n" for s in steps))
        if not confirm("  Go ahead?", assume_yes):
            tn.close()
            sys.exit("Stopped before touching the flash. The script is on the SD card; nothing else changed.")
        if is_symlink:
            for command in (
                "[ -f /tmp/sd/app_init.sh.orig ] || cp /system/app/bin/app_init.sh /tmp/sd/app_init.sh.orig",
                f"rm {APP_INIT}",
                f"cp /system/app/bin/app_init.sh {APP_INIT}",
                f"chmod +x {APP_INIT}",
            ):
                status, output = tn.run(command)
                if status != 0:
                    sys.exit(f"'{command}' failed ({status}): {output}")
        status, output = tn.run(f"cat /tmp/sd/kc002_boot_hook.sh >> {APP_INIT} && sync")
        if status != 0:
            sys.exit(f"appending the boot hook failed ({status}): {output}")
        print("  boot hook installed")

    # Restart the loop so the new script runs now rather than after the next reboot. The v1 script
    # had no pid file, so match by name. The trap keeps the new loop alive past this session's
    # hangup.
    tn.run("ps | grep '[c]apture_loop.sh' | while read pid rest; do kill $pid; done; rm -f /tmp/capture_loop.pid")
    tn.run("mkdir -p /tmp/sd/kc002_photos")
    tn.run("( trap '' HUP; exec /tmp/sd/capture_loop.sh >> /tmp/sd/capture_loop.log 2>&1 ) &")
    time.sleep(1)
    _, running = tn.run("ps | grep '[c]apture_loop.sh'")
    tn.close()
    if not running:
        sys.exit("capture loop did not start — check /tmp/sd/kc002_capture.log on the card")
    print("  capture loop running")

    print("  waiting for the first status report …")
    status_text = None
    ftp = ftp_connect(host)
    for _ in range(15):
        time.sleep(2)
        status_text = ftp_read(ftp, "kc002_photos/_status.txt")
        if status_text:
            break
    ftp.quit()
    if status_text:
        print("\n" + "".join(f"    {line}\n" for line in status_text.splitlines()))
    else:
        print("  no status file yet — give it a minute, then use 'Test connection' in the app")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--sd", type=Path, help="mounted SD card to install onto")
    parser.add_argument("--host", help="camera IP address, to install over the network")
    parser.add_argument("--yes", action="store_true", help="do not ask before modifying the camera's flash")
    args = parser.parse_args()
    if not args.sd and not args.host:
        parser.error("give --sd, --host, or both")

    if args.sd:
        print(f"SD card {args.sd}")
        setup_sd(args.sd)
    if args.host:
        print(f"Camera {args.host}")
        setup_host(args.host, args.yes, skip_upload=False)

    print(
        "\nNext, in the SelfHealth app (Device tab → Cameras → KC002): set the camera IP (or tap Find"
        "\ncamera), give it a unique device id such as kc002_camera_2, register it, and turn sync on."
    )


if __name__ == "__main__":
    main()

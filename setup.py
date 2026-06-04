"""
Script for installing the device.
"""

from nacl.public import PrivateKey
import subprocess
import os

def get_id():
    if 'nt' in os.name:
        return subprocess.Popen('dmidecode.exe -s system-uuid'.split())
    else:
        return subprocess.Popen('hal-get-property --udi /org/freedesktop/Hal/devices/computer --key system.hardware.uuid'.split())

local_sk = PrivateKey.generate()
local_pk = local_sk.public_key

# write the public key to a file
with open(".env", "a") as f:
    f.write(f"DEVICE_PUBLIC_KEY={local_pk.encode().hex()}\n")
    f.write(f"DEVICE_PRIVATE_KEY={local_sk.encode().hex()}\n")
    f.write(f"DEVICE_ID={get_id()}\n")

print(f"Public key: {local_pk.encode().hex()}")
print(f"Private key: {local_sk.encode().hex()}")

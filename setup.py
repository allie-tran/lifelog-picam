"""
Script for installing the device.
"""
from nacl.public import PrivateKey
import subprocess
import os
import uuid


NIL = uuid.UUID(int=0)
def get_id():
    return str(uuid.uuid5(NIL, os.uname().nodename))

local_sk = PrivateKey.generate()
local_pk = local_sk.public_key

# write the public key to a file
with open(".env", "a") as f:
    f.write(f"DEVICE_ID={get_id()}\n")
    f.write(f"DEVICE_PUBLIC_KEY={local_pk.encode().hex()}\n")
    f.write(f"DEVICE_PRIVATE_KEY={local_sk.encode().hex()}\n")

print(f"Public key: {local_pk.encode().hex()}")
print(f"Private key: {local_sk.encode().hex()}")

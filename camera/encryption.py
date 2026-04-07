import nacl.utils
from nacl.public import PrivateKey, Box

# This device
sk = PrivateKey.generate()
pk = sk.public_key

# For the server
sk_server = PrivateKey.generate()
pk_server = sk_server.public_key

print("DEVICE_PUBLIC_KEY=", pk.encode().hex())
print("DEVICE_SECRET_KEY=", sk.encode().hex())

print("SERVER_PUBLIC_KEY=", pk_server.encode().hex())
print("SERVER_SECRET_KEY=", sk_server.encode().hex())


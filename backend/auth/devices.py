import os
from typing import Dict
from datetime import datetime

from fastapi import HTTPException
from jwt.api_jwt import decode, encode
from jwt.exceptions import ExpiredSignatureError, InvalidTokenError

from auth.types import Device

SECRET = os.getenv("JWT_SECRET", "")
assert SECRET, "JWT_SECRET is not set"

def generate_token_for_device(device_id: str) -> bytes:
    """
    Generate a token for the device
    """
    return encode({"device": device_id}, SECRET, algorithm="HS256")


def verify_device_token(token: str) -> Dict[str, str]:
    """
    Verify the device token and return the device_id
    """
    try:
        data = decode(token, SECRET, algorithms=["HS256"])
        if "device" not in data:
            raise HTTPException(status_code=401, detail="Invalid token")

        Device.update_one({
            "device_id": data["device"],
        }, {
            "$set": {
                "last_seen": datetime.utcnow()
            }
        }, upsert=True)
        return data  # type: ignore
    except ExpiredSignatureError:
        raise HTTPException(status_code=401, detail="Token has expired")
    except InvalidTokenError:
        raise HTTPException(status_code=401, detail="Invalid token")

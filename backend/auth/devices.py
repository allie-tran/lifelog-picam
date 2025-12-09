from jwt import decode, encode
from jwt import ExpiredSignatureError, InvalidTokenError
import os
from fastapi import HTTPException, Request
from typing import Dict

from auth.auth_models import find_user_by_username, verify_token
from auth.types import AccessLevel

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
        return data # type: ignore
    except ExpiredSignatureError:
        raise HTTPException(status_code=401, detail="Token has expired")
    except InvalidTokenError:
        raise HTTPException(status_code=401, detail="Invalid token")


def auth_device_dependency(request: Request) -> AccessLevel:
    auth_token = request.headers.get("Authorization")
    if not auth_token:
        raise HTTPException(status_code=401, detail="Missing token")
    auth_token = auth_token.replace("Bearer ", "")
    data = verify_token(auth_token)
    user = find_user_by_username(data["username"])
    if not user:
        raise HTTPException(status_code=401, detail="User does not exist")

    device_id = request.query_params.get("device")
    return user.devices.get(device_id, AccessLevel.NONE)

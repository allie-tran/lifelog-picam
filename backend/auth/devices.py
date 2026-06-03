import os
from typing import Dict

from fastapi import HTTPException
from jwt.api_jwt import decode, encode
from jwt.exceptions import ExpiredSignatureError, InvalidTokenError
from sqlalchemy import select

from database.models import Device, SensorDevice

SECRET = os.getenv("JWT_SECRET", "")
assert SECRET, "JWT_SECRET is not set"

def generate_token_for_device(device_id: str):
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
            print("Token missing 'device' field:", data)
            raise HTTPException(status_code=401, detail="Invalid token")
        print("Ok token for device:", data["device"])
        return data  # type: ignore
    except ExpiredSignatureError:
        print("Token expired:", token)
        raise HTTPException(status_code=401, detail="Token has expired")
    except InvalidTokenError:
        print("Invalid token:", token)
        raise HTTPException(status_code=401, detail="Invalid token")


def verify_device_and_user(session, device_id: str, sensor_type: str):
    user_id = session.execute(select(SensorDevice.associated_user).where(SensorDevice.device_id == device_id, SensorDevice.sensor_type == sensor_type)).scalar_one_or_none()
    if user_id is None:
        print(f"Device {device_id} with sensor type {sensor_type} not found or not associated with a user.")
        raise HTTPException(status_code=401, detail="Device not registered or not associated with a user")

    user_obj = session.execute(select(Device).where(Device.id == user_id)).scalar_one_or_none()
    if not user_obj:
        raise HTTPException(status_code=404, detail="Associated user not found for device. Please register the device first. (device_id: {})".format(device_id))
    return user_obj

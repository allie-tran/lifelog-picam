from fastapi import Depends, FastAPI, HTTPException, Query
from fastapi_limiter.depends import RateLimiter
from pyrate_limiter import Duration, Limiter, Rate
from typing import Annotated

from sqlalchemy import delete, select
from database import get_session

from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import session

from auth.auth_models import (
    auth_dependency,
    get_user,
    create_user,
    find_user_by_username,
    verify_token,
    verify_user,
)
from auth.types import AccessChangeRequest, AccessLevel, CreateUserRequest, LoginRequest, LoginResponse, User, UserResponse
from database.models import Device, SensorDevice
from dependencies import CamelCaseModel

auth_app = FastAPI()

def _require_owner(access_level: AccessLevel):
    if access_level not in (AccessLevel.OWNER, AccessLevel.ADMIN):
        raise HTTPException(status_code=403, detail=f"Not authorized. Owner or Admin access required, but got {access_level}.")


def _require_any_access(access_level: AccessLevel):
    if access_level == AccessLevel.NONE:
        raise HTTPException(status_code=403, detail=f"Not authorized. Access required, but got {access_level}.")


def _require_admin(access_level: AccessLevel):
    if access_level != AccessLevel.ADMIN:
        raise HTTPException(status_code=403, detail="fNot authorized. Admin access required.")

@auth_app.get("/health")
def health_check():
    return {"status": "ok"}

# -----------------------------------------------------------------------
# USERS
# -----------------------------------------------------------------------
@auth_app.post(
    "/register",
    response_model=UserResponse,
    dependencies=[Depends(RateLimiter(limiter=Limiter(Rate(3, 5 * Duration.MINUTE))))],
)
def register(request: CreateUserRequest, session: Annotated[session.Session, Depends(get_session)]):
    """
    Endpoint to create a new user
    """
    # write a log to a file named auth.log
    with open("auth.log", "a") as f:
        f.write(f"Register attempt: email={request.email}, username={request.username}")
        try:
            res = create_user(session, request)
            f.write(f" - success\n")
            return res
        except Exception as e:
            f.write(f" - failed: {str(e)}\n")
            raise e

@auth_app.post("/login", response_model=LoginResponse)
def login(request: LoginRequest):
    """
    Endpoint to verify user credentials and return an access token
    """
    return verify_user(request)

@auth_app.get("/verify", response_model=dict)
def verify(token: str):
    """
    Endpoint to verify the token and return the user
    """

    data = verify_token(token)
    user = find_user_by_username(data["username"])
    if not user:
        raise HTTPException(status_code=401, detail="User does not exist")
    return { "success": True, "username": user.username, "devices": user.devices, "sensors": user.sensors }


# -----------------------------------------------------------------------
# ADMIN
# -----------------------------------------------------------------------
@auth_app.get("/users", response_model=list[UserResponse], dependencies=[Depends(auth_dependency)])
def get_users(user: Annotated[User, Depends(get_user)]):
    """
    Endpoint to get all users
    """
    if not user.is_admin:
        raise HTTPException(status_code=403, detail="Not authorized")
    users = list(User.find({}))
    return [UserResponse.model_validate(u.model_dump()) for u in users]

@auth_app.post("/change-access", dependencies=[Depends(get_user)])
def change_user_access(request: AccessChangeRequest, admin_user: Annotated[User, Depends(get_user)]):
    """
    Endpoint to change user access levels for devices
    """
    if not admin_user.is_admin:
        raise HTTPException(status_code=403, detail="Not authorized")

    user = find_user_by_username(request.username)
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    if not request.device_id:
        raise HTTPException(status_code=400, detail="Device ID is required")

    old_access = {da.device_id: da.access_level for da in user.devices} if user.devices else {}
    updated_access = old_access.copy()
    updated_access[request.device_id] = request.access_level

    User.update_one(
        {"username": request.username},
        {
            "$set": {
                "devices": [
                    {"device_id": did, "access_level": al} for did, al in updated_access.items()
                ]
            }
        },
    )
    return True

class SensorDeviceRequest(CamelCaseModel):
    device_id: str
    device_nickname: str | None
    sensor_type: str
    secret: str | None = None
    associated_username: str

@auth_app.put("/add-sensor", dependencies=[Depends(get_user)])
def add_sensor(request: SensorDeviceRequest, user: Annotated[User, Depends(get_user)], session: session.Session = Depends(get_session)):
    """
    Endpoint to add a new device to a user
    """
    device_id = request.device_id
    device_nickname = request.device_nickname or device_id
    sensor_type = request.sensor_type
    secret = request.secret
    associated_username = request.associated_username

    if not user.is_admin:
        raise HTTPException(status_code=403, detail="Not authorized")

    user_obj = session.execute(select(Device).where(Device.device_id == associated_username)).scalar_one_or_none()
    stmt = insert(SensorDevice).values(
        device_id=device_id,
        device_nickname=device_nickname,
        sensor_type=sensor_type,
        secret=secret,
        associated_user=user_obj.id if user_obj else None,
    ).on_conflict_do_update(constraint="uq_sensor_device_id_type", set_={
        "device_nickname": device_nickname,
        "secret": secret,
        "associated_user": user_obj.id if user_obj else None,
    })
    session.execute(stmt)
    session.commit()
    print(f"Added/Updated device {device_id} for user {associated_username}")

    # MongoDB
    # Remove all existing access for this device
    User.update_many(
        {},
        {"$pull": {"sensors": {"device_id": device_id, "sensor_type": sensor_type}}}
    )

    # Add owner access for the associated user
    User.update_one(
        {"username": associated_username},
        {"$push": {"sensors": {"device_id": device_id, "device_nickname": device_nickname, "sensor_type": sensor_type}}}
    )
    return {"success": True, "message": f"Device {device_id} added/updated and access granted to user {associated_username}"}


@auth_app.delete("/remove-access", dependencies=[Depends(get_user)])
def remove_device_access(
    username: str = Query(...),
    device_id: str = Query(...),
    admin_user: User = Depends(get_user),
):
    if not admin_user.is_admin:
        raise HTTPException(status_code=403, detail="Not authorized")

    user = find_user_by_username(username)
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    updated_devices = [d for d in (user.devices or []) if d.device_id != device_id]
    User.update_one(
        {"username": username},
        {"$set": {"devices": [{"device_id": d.device_id, "access_level": d.access_level} for d in updated_devices]}},
    )
    return {"success": True}


@auth_app.delete("/remove-sensor", dependencies=[Depends(get_user)])
def remove_sensor_access(
    username: str = Query(...),
    device_id: str = Query(...),
    sensor_type: str = Query(...),
    admin_user: User = Depends(get_user),
    db_session: session.Session = Depends(get_session),
):
    if not admin_user.is_admin:
        raise HTTPException(status_code=403, detail="Not authorized")

    db_session.execute(
        delete(SensorDevice).where(
            SensorDevice.device_id == device_id,
            SensorDevice.sensor_type == sensor_type,
        )
    )
    db_session.commit()

    User.update_one(
        {"username": username},
        {"$pull": {"sensors": {"device_id": device_id, "sensor_type": sensor_type}}},
    )
    return {"success": True}

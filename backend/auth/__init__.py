from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi_limiter.depends import RateLimiter
from pyrate_limiter import Duration, Limiter, Rate
from typing import Annotated

import os
from datetime import datetime

from nacl.public import PrivateKey
from sqlalchemy import delete, func, select, update as sa_update
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
from auth.types import AccessChangeRequest, AccessLevel, CreateUserRequest, LoginRequest, LoginResponse, SensorStatus, User, UserResponse
from database.models import Device, SensorDevice
from core.dependencies import CamelCaseModel

router = APIRouter()

def _require_owner(access_level: AccessLevel):
    if access_level not in (AccessLevel.OWNER, AccessLevel.ADMIN):
        raise HTTPException(status_code=403, detail=f"Not authorized. Owner or Admin access required, but got {access_level}.")


def _require_any_access(access_level: AccessLevel):
    if access_level == AccessLevel.NONE:
        raise HTTPException(status_code=403, detail=f"Not authorized. Access required, but got {access_level}.")


def _require_admin(access_level: AccessLevel):
    if access_level != AccessLevel.ADMIN:
        raise HTTPException(status_code=403, detail="Not authorized. Admin access required.")

@router.get("/health")
def health_check():
    return {"status": "ok"}

# -----------------------------------------------------------------------
# USERS
# -----------------------------------------------------------------------
@router.post(
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

@router.post("/login", response_model=LoginResponse)
def login(request: LoginRequest):
    """
    Endpoint to verify user credentials and return an access token
    """
    return verify_user(request)

@router.get("/verify", response_model=dict)
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
@router.get("/users", response_model=list[UserResponse], dependencies=[Depends(auth_dependency)])
def get_users(user: Annotated[User, Depends(get_user)]):
    """
    Endpoint to get all users
    """
    if not user.is_admin:
        raise HTTPException(status_code=403, detail="Not authorized")
    users = list(User.find({}))
    return [UserResponse.model_validate(u.model_dump()) for u in users]

@router.post("/change-access", dependencies=[Depends(get_user)])
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


def _user_device_id(db_session: session.Session, username: str):
    """Row id of the `devices` entry that stands for a user, which is what SensorDevice points at."""
    return db_session.execute(
        select(Device.id).where(Device.device_id == username)
    ).scalar_one_or_none()

@router.put("/add-sensor", dependencies=[Depends(get_user)])
def add_sensor(request: SensorDeviceRequest, user: Annotated[User, Depends(get_user)], session: session.Session = Depends(get_session)):
    """
    Endpoint to add a new device to a user
    """
    device_id = request.device_id
    device_nickname = request.device_nickname or device_id
    sensor_type = request.sensor_type
    secret = request.secret
    associated_username = request.associated_username

    # Admins register sensors for anyone; everyone else may only claim a sensor for themselves,
    # and only one nobody else already holds. This is what lets a phone/glasses client register
    # itself after signing in, instead of needing an admin to do it out of band.
    if not user.is_admin:
        if associated_username != user.username:
            raise HTTPException(status_code=403, detail="Not authorized to register a sensor for another user")
        owner_id = _user_device_id(session, user.username)
        existing_owner = session.execute(
            select(SensorDevice.associated_user).where(
                SensorDevice.device_id == device_id,
                SensorDevice.sensor_type == sensor_type,
            )
        ).scalar_one_or_none()
        if existing_owner is not None and existing_owner != owner_id:
            raise HTTPException(status_code=409, detail="Sensor is already registered to another user")

    user_obj = session.execute(select(Device).where(Device.device_id == associated_username)).scalar_one_or_none()
    stmt = insert(SensorDevice).values(
        device_id=device_id,
        device_nickname=device_nickname,
        sensor_type=sensor_type,
        secret=secret,
        associated_user=user_obj.id if user_obj else None,
    )
    stmt = stmt.on_conflict_do_update(constraint="uq_sensor_device_id_type", set_={
        "device_nickname": device_nickname,
        # Re-registering must not wipe a provisioned encryption key: only an explicit secret in
        # the request replaces the stored one.
        "secret": func.coalesce(stmt.excluded.secret, SensorDevice.secret),
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


@router.delete("/remove-access", dependencies=[Depends(get_user)])
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


def _owns_sensor(user: User, device_id: str, sensor_type: str) -> bool:
    return any(
        s.device_id == device_id and s.sensor_type == sensor_type
        for s in (user.sensors or [])
    )


@router.delete("/remove-sensor", dependencies=[Depends(get_user)])
def remove_sensor_access(
    username: str = Query(...),
    device_id: str = Query(...),
    sensor_type: str = Query(...),
    admin_user: User = Depends(get_user),
    db_session: session.Session = Depends(get_session),
):
    # Admin can remove any sensor; a user may remove a sensor they own.
    if not admin_user.is_admin and not (
        username == admin_user.username and _owns_sensor(admin_user, device_id, sensor_type)
    ):
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


@router.get("/my-sensors", response_model=list[SensorStatus], dependencies=[Depends(get_user)])
def my_sensors(
    user: User = Depends(get_user),
    db_session: session.Session = Depends(get_session),
):
    """List the logged-in user's sensor devices, enriched with last-seen from Postgres."""
    sensors = user.sensors or []
    if not sensors:
        return []
    device_ids = [s.device_id for s in sensors]
    rows = db_session.execute(
        select(SensorDevice.device_id, SensorDevice.sensor_type, SensorDevice.last_seen)
        .where(SensorDevice.device_id.in_(device_ids))
    ).all()
    last_seen_map = {(d, t): ls for d, t, ls in rows}
    return [
        SensorStatus(
            device_id=s.device_id,
            device_nickname=s.device_nickname,
            sensor_type=s.sensor_type,
            last_seen=last_seen_map.get((s.device_id, s.sensor_type)),
        )
        for s in sensors
    ]


class SensorRegistrationResponse(CamelCaseModel):
    device_id: str
    sensor_type: str
    registered: bool
    owned_by_me: bool
    device_nickname: str | None = None
    last_seen: datetime | None = None
    has_secret: bool = False


async def _optional_user(request: Request) -> User | None:
    """The caller's account if they sent a usable token, otherwise None — never raises."""
    if not request.headers.get("Authorization"):
        return None
    try:
        return await get_user(request)
    except HTTPException:
        return None


@router.get(
    "/sensor-registration",
    response_model=SensorRegistrationResponse,
    dependencies=[Depends(RateLimiter(limiter=Limiter(Rate(60, Duration.MINUTE))))],
)
async def sensor_registration(
    device_id: str = Query(...),
    sensor_type: str = Query(...),
    user: User | None = Depends(_optional_user),
    db_session: session.Session = Depends(get_session),
):
    """
    Whether a device id is registered for a sensor type, and whether it belongs to the caller.

    Uploads from an unregistered device are rejected (see auth.devices.verify_device_and_user), so
    a client needs this to tell "nothing is being ingested" apart from "capture is broken". That
    question has to be answerable before signing in — a device that was never registered is
    exactly the case where nobody is signed in yet — so an anonymous caller gets the bare
    registered yes/no and nothing else. Ownership, nickname, last-seen and key state need a token,
    and no caller is ever told which account holds a sensor that is not theirs.
    """
    row = db_session.execute(
        select(SensorDevice).where(
            SensorDevice.device_id == device_id,
            SensorDevice.sensor_type == sensor_type,
        )
    ).scalar_one_or_none()

    if row is None:
        return SensorRegistrationResponse(
            device_id=device_id, sensor_type=sensor_type, registered=False, owned_by_me=False
        )

    # Ownership is the association itself, never the caller's role: an admin asking about a device
    # that belongs to somebody else must be told so, otherwise a client signed in as admin reports
    # every device on the system as its own.
    owned_by_me = (
        user is not None
        and row.associated_user is not None
        and row.associated_user == _user_device_id(db_session, user.username)
    )
    # Admins may see the details of any sensor; everyone else only their own.
    show_details = owned_by_me or (user is not None and user.is_admin)
    return SensorRegistrationResponse(
        device_id=device_id,
        sensor_type=sensor_type,
        registered=row.associated_user is not None,
        owned_by_me=owned_by_me,
        device_nickname=row.device_nickname if show_details else None,
        last_seen=row.last_seen if show_details else None,
        has_secret=bool(row.secret) if show_details else False,
    )


class SensorKeyRequest(CamelCaseModel):
    device_id: str
    sensor_type: str = "camera"


class SensorKeyResponse(CamelCaseModel):
    device_id: str
    sensor_type: str
    device_secret_key: str
    server_public_key: str


@router.post("/sensor-key", response_model=SensorKeyResponse, dependencies=[Depends(get_user)])
def generate_sensor_key(
    request: SensorKeyRequest,
    user: User = Depends(get_user),
    db_session: session.Session = Depends(get_session),
):
    """
    Mint a NaCl box keypair for a sensor: the device keeps the secret key, the server stores the
    public key on the sensor row and decrypts uploads with it (see routers/images.py).

    The secret key is returned exactly once and never stored server-side, so calling this again
    rotates the key and invalidates whatever the device held before.
    """
    device_id = request.device_id
    sensor_type = request.sensor_type

    # Checked against sensor_devices rather than the user document's sensor list: the row is what
    # upload auth reads, and the two can drift if a sensor is reassigned directly in Postgres.
    owner = db_session.execute(
        select(SensorDevice.associated_user).where(
            SensorDevice.device_id == device_id,
            SensorDevice.sensor_type == sensor_type,
        )
    ).scalar_one_or_none()
    if not user.is_admin and (owner is None or owner != _user_device_id(db_session, user.username)):
        raise HTTPException(status_code=403, detail="Register the sensor to your account first")

    server_secret_key = os.getenv("SERVER_SECRET_KEY", "")
    if not server_secret_key:
        raise HTTPException(status_code=500, detail="Server encryption key is not configured")

    device_key = PrivateKey.generate()
    result = db_session.execute(
        sa_update(SensorDevice)
        .where(SensorDevice.device_id == device_id, SensorDevice.sensor_type == sensor_type)
        .values(secret=bytes(device_key.public_key).hex())
    )
    if result.rowcount == 0:
        raise HTTPException(status_code=404, detail="Sensor not found")
    db_session.commit()

    server_public_key = bytes(PrivateKey(bytes.fromhex(server_secret_key)).public_key).hex()
    return SensorKeyResponse(
        device_id=device_id,
        sensor_type=sensor_type,
        device_secret_key=bytes(device_key).hex(),
        server_public_key=server_public_key,
    )


@router.put("/rename-sensor", dependencies=[Depends(get_user)])
def rename_sensor(
    device_id: str = Query(...),
    sensor_type: str = Query(...),
    nickname: str = Query(...),
    user: User = Depends(get_user),
    db_session: session.Session = Depends(get_session),
):
    """Rename a sensor device. Admin can rename any; a user may rename a sensor they own."""
    if not user.is_admin and not _owns_sensor(user, device_id, sensor_type):
        raise HTTPException(status_code=403, detail="Not authorized")

    db_session.execute(
        sa_update(SensorDevice)
        .where(SensorDevice.device_id == device_id, SensorDevice.sensor_type == sensor_type)
        .values(device_nickname=nickname)
    )
    db_session.commit()

    User.update_one(
        {"username": user.username, "sensors.device_id": device_id, "sensors.sensor_type": sensor_type},
        {"$set": {"sensors.$.device_nickname": nickname}},
    )
    return {"success": True, "deviceNickname": nickname}

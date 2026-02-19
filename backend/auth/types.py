from app_types import CustomTarget
from dependencies import CamelCaseModel
from mongodb_odm import Document
from datetime import datetime
try:
    from enum import StrEnum
except ImportError:
    import enum
    class StrEnum(str, enum.Enum):
        pass

class AccessLevel(StrEnum):
    OWNER = "owner"
    VIEWER = "viewer"
    ADMIN = "admin"
    NONE = "none"

class DeviceAccess(CamelCaseModel):
    device_id: str
    access_level: AccessLevel = AccessLevel.NONE

class CreateUserRequest(CamelCaseModel):
    username: str
    email: str
    password: str

    admin_code: str | None = None

class LoginRequest(CamelCaseModel):
    username: str
    password: str

class LoginResponse(CamelCaseModel):
    token: str
    token_type: str = "bearer"
    username: str | None = None
    devices: list[DeviceAccess] | None = None

class AccessChangeRequest(CamelCaseModel):
    username: str
    device_id: str
    access_level: AccessLevel

class User(Document):
    username: str
    email: str
    password: str # hashed password
    is_admin: bool = False
    devices: list[DeviceAccess] | None = None
    goal_targets: list[CustomTarget] = []

    class ODMConfig(Document.ODMConfig):
        collection_name = "users"

class UserResponse(CamelCaseModel):
    username: str
    email: str
    is_admin: bool
    devices: list[DeviceAccess] | None = None

class Person(CamelCaseModel):
    name: str
    embedding: list[float]

class Device(Document):
    device_id: str
    public_key: str = ""
    last_seen: datetime | None = None
    whitelist: list[Person] = []

    class ODMConfig(Document.ODMConfig):
        collection_name = "devices"

class DeviceResponse(CamelCaseModel):
    device_id: str

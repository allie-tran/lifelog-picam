from pydantic import field_validator
from schemas import CustomTarget
from core.dependencies import CamelCaseModel
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

class SensorType(StrEnum):
    CAMERA = "camera"
    BIOMETRICS = "biometrics"
    LOCATION = "location"

class SensorDeviceWithDate(CamelCaseModel):
    device_id: str
    device_nickname: str | None = None
    sensor_type: SensorType

class SensorStatus(CamelCaseModel):
    device_id: str
    device_nickname: str | None = None
    sensor_type: str
    last_seen: datetime | None = None
class LoginResponse(CamelCaseModel):
    token: str
    token_type: str = "bearer"
    username: str | None = None
    devices: list[DeviceAccess] | None = None
    sensors: list[SensorDeviceWithDate] | None = None

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
    sensors: list[SensorDeviceWithDate] | None = None
    goal_targets: list[CustomTarget] = []

    class ODMConfig(Document.ODMConfig):
        collection_name = "users"

class UserResponse(CamelCaseModel):
    username: str
    email: str
    is_admin: bool
    devices: list[DeviceAccess] | None = None
    sensors: list[SensorDeviceWithDate] | None = None

class Person(CamelCaseModel):
    name: str
    embeddings: list[list[float]] = []
    cropped: list[str]
    cluster_id: str | None = None

    # convert cluster_id to string for easier storage in MongoDB, since it can be None or a string
    @field_validator("cluster_id", mode="before")
    def validate_cluster_id(cls, v):
        if v is None:
            return None
        return str(v)


# class Device(Document):
#     device_id: str
#     public_key: str = ""
#     last_seen: datetime | None = None
#     whitelist: list[Person] = []
#     transform_matrix: bytes | None = None

#     class ODMConfig(Document.ODMConfig):
#         collection_name = "devices"

class DeviceResponse(CamelCaseModel):
    device_id: str

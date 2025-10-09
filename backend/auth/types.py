from dependencies import CamelCaseModel
from mongodb_odm import Document

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

class User(Document):
    username: str
    email: str
    password: str # hashed password

    class ODMConfig(Document.ODMConfig):
        collection_name = "users"


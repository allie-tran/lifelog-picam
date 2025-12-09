import os
from typing import Dict

import bcrypt
import jwt
import redis
from fastapi import HTTPException, Request
from rich import print
from dotenv import load_dotenv

from auth.types import CreateUserRequest, LoginRequest, LoginResponse, User, AccessLevel
from configs import REDIS_HOST, REDIS_PORT
from settings.utils import create_device

load_dotenv()
SECRET = os.getenv("JWT_SECRET", "")
assert SECRET, "JWT_SECRET is not set"

# Remove all redis keys
def flush_redis() -> None:
    r = redis.Redis(host=REDIS_HOST, port=REDIS_PORT, decode_responses=True)
    r.flushall()
    print("Redis flushed")

# flush_redis()
def create_user(request: CreateUserRequest, overwrite=False) -> User:
    """
    Create a new user
    """
    if not request.admin_code or request.admin_code not in os.getenv("ADMIN_PASSWORD", "").split(","):
        raise HTTPException(status_code=403, detail="You are not authorized to create a user")

    if User.find_one({"username": request.username}) and not overwrite:
        raise HTTPException(status_code=400, detail="User already exists")

    create_device(request.username)
    User.update_one(
        {"username": request.username},
        {
            "$set": {
                "password": bcrypt.hashpw(request.password.encode(), bcrypt.gensalt()),
                "email": request.username,
                "devices": [
                    {"device_id": request.username, "access_level": "owner"}
                ],
            }
        },
        upsert=True,
    )
    print(f"User {request.username} created")
    return find_user_by_username(request.username)


def generate_token(username: str):
    """
    Generate a token for the user
    """
    return jwt.encode(
        {"username": username}, SECRET, algorithm="HS256"
    )


def find_user_by_username(username: str) -> User:
    """
    Find a user by username
    """
    user = User.find_one({"username": username})
    if not user:
        raise HTTPException(status_code=401, detail="User does not exist")
    return user


def verify_user(request: LoginRequest) -> LoginResponse:
    """
    Verify user credentials and return an access token
    """
    user = User.find_one({"username": request.username})
    if not user:
        print("User not found:", request.username)
        raise HTTPException(status_code=401, detail="User does not exist")
    if bcrypt.checkpw(request.password.encode(), bytes(user.password, "utf-8")):
        return LoginResponse(
            token=generate_token(request.username),
            token_type="bearer",
        )
    else:
        raise HTTPException(status_code=401, detail="Invalid credentials")


def verify_token(token: str) -> Dict[str, str]:
    """
    Verify the token and return the username
    """
    try:
        data = jwt.decode(token, SECRET, algorithms=["HS256"])
        if "username" not in data:
            raise HTTPException(status_code=401, detail="Invalid token")
        return data
    except jwt.ExpiredSignatureError:
        raise HTTPException(status_code=401, detail="Token is expired")
    except jwt.InvalidTokenError:
        raise HTTPException(status_code=401, detail="Invalid token")


async def get_user(request: Request) -> User:
    """
    Get the user from the request to make sure the user is authenticated
    """
    token = request.headers.get("Authorization")  # Bearer token
    if not token:
        raise HTTPException(status_code=401, detail="Please log in")
    username = verify_token(token.split(" ")[1])["username"]
    if not username:
        raise HTTPException(status_code=401, detail="Invalid token")

    user = find_user_by_username(username)
    return user

def auth_dependency(request: Request):
    token = request.headers.get("Authorization")
    if not token:
        raise HTTPException(status_code=401, detail="Missing token")
    token = token.replace("Bearer ", "")
    data = verify_token(token)
    user = find_user_by_username(data["username"])
    if not user:
        raise HTTPException(status_code=401, detail="User does not exist")
    devices = user.devices or []
    device = request.query_params.get("device")
    for d in devices:
        if d.device_id == device:
            return d.access_level
    return AccessLevel.NONE

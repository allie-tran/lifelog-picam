from fastapi import Depends, FastAPI, HTTPException
from fastapi_limiter.depends import RateLimiter
from typing import Annotated

from auth.auth_models import (
    auth_dependency,
    get_user,
    create_user,
    find_user_by_username,
    verify_token,
    verify_user,
)
from auth.types import AccessChangeRequest, CreateUserRequest, LoginRequest, LoginResponse, User, UserResponse

auth_app = FastAPI()


@auth_app.get("/health")
def health_check():
    return {"status": "ok"}

@auth_app.post(
    "/register",
    response_model=UserResponse,
    dependencies=[Depends(RateLimiter(times=3, seconds=60))],
)
def register(request: CreateUserRequest):
    """
    Endpoint to create a new user
    """
    # write a log to a file named auth.log
    with open("auth.log", "a") as f:
        f.write(f"Register attempt: email={request.email}, username={request.username}")
        try:
            res = create_user(request)
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
    return { "success": True, "username": user.username, "devices": user.devices }


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


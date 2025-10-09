from fastapi import Depends, FastAPI, HTTPException
from fastapi_limiter.depends import RateLimiter

from auth.auth_models import (
    create_user,
    find_user_by_username,
    verify_token,
    verify_user,
)
from auth.types import CreateUserRequest, LoginRequest, LoginResponse, User

auth_app = FastAPI()

@auth_app.get("/health")
def health_check():
    return {"status": "ok"}

@auth_app.post(
    "/register",
    response_model=User,
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
    return { "success": True, "username": user.username, "email": user.email }

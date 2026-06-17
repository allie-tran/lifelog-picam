
from typing import Annotated, Optional
from bson import ObjectId as _ObjectId
from fastapi import Request
from joblib import Memory
from pydantic import AfterValidator, BaseModel, Field
from pydantic.alias_generators import to_camel


def client_ip(request: Request) -> Optional[str]:
    """Real client IP. Behind a proxy (e.g. nginx /be) it's in X-Forwarded-For."""
    fwd = request.headers.get("x-forwarded-for")
    if fwd:
        return fwd.split(",")[0].strip()
    return request.client.host if request.client else None

memory = Memory("cachedir")


def check_object_id(value: str) -> str:
    if not _ObjectId.is_valid(value):
        raise ValueError("Invalid ObjectId")
    return value


ObjectId = Annotated[
    str,
    Field(..., alias="_id", description="MongoDB ObjectId"),
    AfterValidator(check_object_id),
]


class CamelCaseModel(BaseModel):

    class Config:
        alias_generator = to_camel
        populate_by_name = True
        str_strip_whitespace = True




from typing import Annotated
from bson import ObjectId as _ObjectId
from joblib import Memory
from pydantic import AfterValidator, BaseModel, Field
from pydantic.alias_generators import to_camel

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



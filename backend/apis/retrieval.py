import os
from typing import Annotated
from PIL import UnidentifiedImageError
from fastapi import Depends, FastAPI, HTTPException, UploadFile
from sqlalchemy.orm import Session

from app_types.search import SearchQuery
from auth.auth_models import auth_dependency
from auth.types import AccessLevel
from constants import DIR
from database import get_session
from auth import _require_owner
from preprocess import get_similar_images, retrieve_image_with_filters

app = FastAPI()
@app.get("/health")
def health_check():
    return {"status": "ok"}

@app.post("/search-images")
def search(
    device: str,
    request: SearchQuery,
    sort_by: str = "relevance",
    access_level: Annotated[AccessLevel, Depends(auth_dependency)] = AccessLevel.NONE,
    session: Session = Depends(get_session),
):
    _require_owner(access_level)

    print(f"Received search query for device {device}: {request}")
    if request.empty:
        return []

    # return retrieve_image(
    #     session,
    #     device,
    #     request.text,
    #     sort_by,
    #     k=1000,
    # )
    return retrieve_image_with_filters(
        session,
        device,
        request,
        sort_by,
        k=1000,
    )


@app.get("/similar-images")
def similar_images(
    image: str,
    device: str,
    access_level: Annotated[AccessLevel, Depends(auth_dependency)] = AccessLevel.NONE,
    session: Session = Depends(get_session),
):
    _require_owner(access_level)

    return get_similar_images(
        session,
        device,
        image,
        k=1000,
    )


@app.post("/similar-images")
def similar_images_by_upload(
    file: UploadFile,
    device: str,
    access_level: Annotated[AccessLevel, Depends(auth_dependency)] = AccessLevel.NONE,
    session: Session = Depends(get_session),
):
    _require_owner(access_level)

    temp_path = f"{DIR}/{device}/temp_{file.filename}"

    with open(temp_path, "wb") as f:
        f.write(file.file.read())
    try:
        results = get_similar_images(
            session,
            device,
            temp_path,
            k=1000,
        )

    except UnidentifiedImageError:
        raise HTTPException(status_code=400, detail="Invalid image file.")
    finally:
        os.remove(temp_path)

    return results


"""
feedback.py — unified user feedback: ratings, content flags, free-text reports.

All three kinds share one store (`user_feedback`). Ratings upsert (one per user
per target); flags/reports insert a review row (status=open) for admins.
"""

from datetime import datetime, timezone
from typing import Annotated, Any, Optional

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from auth import _require_admin, _require_any_access, _require_owner
from auth.auth_models import auth_dependency, get_user
from auth.types import AccessLevel
from core.dependencies import CamelCaseModel
from database import get_session
from database.models import FeedbackKind, FeedbackStatus, UserFeedback

router = APIRouter()


@router.get("/health")
def health_check():
    return {"status": "ok"}


# ---------------------------------------------------------------------------
# Schemas
# ---------------------------------------------------------------------------


class FeedbackSubmit(CamelCaseModel):
    kind: FeedbackKind
    target_type: Optional[str] = None   # search | segment | day_summary | image
    target_id: Optional[str] = None
    value: Optional[str] = None         # up/down for rating; reason slug for flag
    comment: Optional[str] = None
    meta: Optional[Any] = None


class FeedbackStatusUpdate(CamelCaseModel):
    status: FeedbackStatus


def _serialize(fb: UserFeedback) -> dict:
    return {
        "id": str(fb.id),
        "username": fb.username,
        "deviceId": fb.device_id,
        "kind": fb.kind.value if fb.kind else None,
        "targetType": fb.target_type,
        "targetId": fb.target_id,
        "value": fb.value,
        "comment": fb.comment,
        "meta": fb.meta,
        "status": fb.status.value if fb.status else None,
        "createdAt": fb.created_at.isoformat() if fb.created_at else None,
        "updatedAt": fb.updated_at.isoformat() if fb.updated_at else None,
    }


# ---------------------------------------------------------------------------
# Submit (any authenticated user)
# ---------------------------------------------------------------------------


@router.post("/submit")
def submit_feedback(
    payload: FeedbackSubmit,
    device: Optional[str] = None,
    access_level: Annotated[AccessLevel, Depends(auth_dependency)] = AccessLevel.NONE,
    user=Depends(get_user),
    session: Session = Depends(get_session),
):
    # Reports are global ("message us") — any logged-in user may send one.
    # Ratings/flags act on a device's data, so require ownership of that device.
    if payload.kind == FeedbackKind.REPORT:
        _require_any_access(access_level)
    else:
        _require_owner(access_level)

    # Ratings upsert on (username, target_type, target_id); value=None un-rates.
    if payload.kind == FeedbackKind.RATING:
        existing = session.execute(
            select(UserFeedback).where(
                UserFeedback.username == user.username,
                UserFeedback.kind == FeedbackKind.RATING,
                UserFeedback.target_type == payload.target_type,
                UserFeedback.target_id == payload.target_id,
            )
        ).scalar_one_or_none()

        if payload.value is None:
            if existing is not None:
                session.delete(existing)
                session.commit()
            return {"message": "Rating removed.", "value": None}

        if existing is not None:
            existing.value = payload.value
            existing.comment = payload.comment
            existing.meta = payload.meta
            existing.device_id = device
            session.commit()
            return {"message": "Rating updated.", "id": str(existing.id), "value": existing.value}

        fb = UserFeedback(
            username=user.username,
            device_id=device,
            kind=FeedbackKind.RATING,
            target_type=payload.target_type,
            target_id=payload.target_id,
            value=payload.value,
            comment=payload.comment,
            meta=payload.meta,
            status=FeedbackStatus.OPEN,
        )
        session.add(fb)
        session.commit()
        return {"message": "Rating saved.", "id": str(fb.id), "value": fb.value}

    # Flags / reports always create a fresh review row.
    fb = UserFeedback(
        username=user.username,
        device_id=device,
        kind=payload.kind,
        target_type=payload.target_type,
        target_id=payload.target_id,
        value=payload.value,
        comment=payload.comment,
        meta=payload.meta,
        status=FeedbackStatus.OPEN,
    )
    session.add(fb)
    session.commit()
    return {"message": "Feedback submitted.", "id": str(fb.id)}


# ---------------------------------------------------------------------------
# My ratings (owner) — lets the UI show active thumb state
# ---------------------------------------------------------------------------


@router.get("/mine")
def my_feedback(
    target_type: Optional[str] = None,
    access_level: Annotated[AccessLevel, Depends(auth_dependency)] = AccessLevel.NONE,
    user=Depends(get_user),
    session: Session = Depends(get_session),
):
    _require_any_access(access_level)

    stmt = select(UserFeedback).where(
        UserFeedback.username == user.username,
        UserFeedback.kind == FeedbackKind.RATING,
    )
    if target_type:
        stmt = stmt.where(UserFeedback.target_type == target_type)
    rows = session.execute(stmt).scalars().all()
    return [_serialize(r) for r in rows]


# ---------------------------------------------------------------------------
# Admin review queue
# ---------------------------------------------------------------------------


@router.get("/list")
def list_feedback(
    kind: Optional[FeedbackKind] = None,
    status: Optional[FeedbackStatus] = None,
    limit: int = 200,
    access_level: Annotated[AccessLevel, Depends(auth_dependency)] = AccessLevel.NONE,
    session: Session = Depends(get_session),
):
    _require_admin(access_level)

    stmt = select(UserFeedback)
    if kind is not None:
        stmt = stmt.where(UserFeedback.kind == kind)
    if status is not None:
        stmt = stmt.where(UserFeedback.status == status)
    stmt = stmt.order_by(UserFeedback.created_at.desc()).limit(limit)
    rows = session.execute(stmt).scalars().all()
    return [_serialize(r) for r in rows]


@router.patch("/{feedback_id}/status")
def update_feedback_status(
    feedback_id: str,
    payload: FeedbackStatusUpdate,
    access_level: Annotated[AccessLevel, Depends(auth_dependency)] = AccessLevel.NONE,
    session: Session = Depends(get_session),
):
    _require_admin(access_level)

    fb = session.execute(
        select(UserFeedback).where(UserFeedback.id == feedback_id)
    ).scalar_one_or_none()
    if fb is None:
        raise HTTPException(status_code=404, detail="Feedback not found")

    fb.status = payload.status
    fb.updated_at = datetime.now(timezone.utc)
    session.commit()
    return _serialize(fb)

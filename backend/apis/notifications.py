"""
notifications.py — REST endpoints for in-app notifications.

GET  /notifications            list (newest first, optional unread_only)
GET  /notifications/unread-count   fast badge count
POST /notifications/mark-read  mark a list of IDs as read
POST /notifications/mark-all-read  mark all for device as read
"""
from __future__ import annotations

import logging
from typing import Annotated, List, Optional

from fastapi import Depends, FastAPI, Query
from sqlalchemy import select, update, func
from sqlalchemy.orm import Session

from auth.auth_models import auth_dependency
from auth.types import AccessLevel
from auth import _require_owner
from database import get_session
from database.models import Notification
from dependencies import CamelCaseModel

app = FastAPI()
logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Response / request models
# ---------------------------------------------------------------------------
class NotificationOut(CamelCaseModel):
    id: str
    device: str
    date: str
    timestamp: Optional[str] = None
    read: bool
    type: str
    title: str
    body: Optional[str] = None
    image_path: Optional[str] = None
    segment_id: Optional[int] = None

    @classmethod
    def from_orm(cls, n: Notification) -> "NotificationOut":
        return cls(
            id=str(n.id),
            device=n.device,
            date=n.date,
            timestamp=n.timestamp.isoformat() if n.timestamp else None,
            read=n.read,
            type=n.type,
            title=n.title,
            body=n.body,
            image_path=n.image_path,
            segment_id=n.segment_id,
        )


class MarkReadRequest(CamelCaseModel):
    ids: List[str]


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------
@app.get("/notifications", response_model=List[NotificationOut])
def list_notifications(
    device: str,
    unread_only: bool = Query(default=False),
    limit: int = Query(default=50, le=200),
    access_level: Annotated[AccessLevel, Depends(auth_dependency)] = AccessLevel.NONE,
    session: Session = Depends(get_session),
):
    _require_owner(access_level)

    stmt = (
        select(Notification)
        .where(Notification.device == device)
        .order_by(Notification.timestamp.desc())
        .limit(limit)
    )
    if unread_only:
        stmt = stmt.where(Notification.read == False)

    rows = session.execute(stmt).scalars().all()
    return [NotificationOut.from_orm(n) for n in rows]


@app.get("/notifications/unread-count")
def unread_count(
    device: str,
    access_level: Annotated[AccessLevel, Depends(auth_dependency)] = AccessLevel.NONE,
    session: Session = Depends(get_session),
):
    _require_owner(access_level)
    count = session.execute(
        select(func.count(Notification.id))
        .where(Notification.device == device, Notification.read == False)
    ).scalar_one()
    return {"count": count}


@app.post("/notifications/mark-read")
def mark_read(
    request: MarkReadRequest,
    device: str,
    access_level: Annotated[AccessLevel, Depends(auth_dependency)] = AccessLevel.NONE,
    session: Session = Depends(get_session),
):
    _require_owner(access_level)
    import uuid as _uuid
    ids = [_uuid.UUID(i) for i in request.ids]
    session.execute(
        update(Notification)
        .where(Notification.id.in_(ids), Notification.device == device)
        .values(read=True)
    )
    session.commit()
    return {"marked": len(ids)}


@app.post("/notifications/mark-all-read")
def mark_all_read(
    device: str,
    access_level: Annotated[AccessLevel, Depends(auth_dependency)] = AccessLevel.NONE,
    session: Session = Depends(get_session),
):
    _require_owner(access_level)
    session.execute(
        update(Notification)
        .where(Notification.device == device, Notification.read == False)
        .values(read=True)
    )
    session.commit()
    return {"ok": True}

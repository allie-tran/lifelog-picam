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

from fastapi import Depends, APIRouter, Query
from sqlalchemy import delete as sa_delete, select, update, func
from sqlalchemy.orm import Session

from auth.auth_models import auth_dependency
from auth.types import AccessLevel
from auth import _require_owner
from database import get_session
from database.models import Notification, PushSubscription
from core.dependencies import CamelCaseModel

router = APIRouter()
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


class PushKeys(CamelCaseModel):
    p256dh: str
    auth: str


class PushSubscriptionIn(CamelCaseModel):
    endpoint: str
    keys: PushKeys


class PushUnsubscribeIn(CamelCaseModel):
    endpoint: str


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------
@router.get("/notifications", response_model=List[NotificationOut])
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


@router.get("/notifications/unread-count")
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


@router.post("/notifications/mark-read")
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


@router.post("/notifications/mark-all-read")
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


@router.post("/notifications/clear-all")
def clear_all(
    device: str,
    access_level: Annotated[AccessLevel, Depends(auth_dependency)] = AccessLevel.NONE,
    session: Session = Depends(get_session),
):
    """Delete every notification for the device."""
    _require_owner(access_level)
    result = session.execute(
        sa_delete(Notification).where(Notification.device == device)
    )
    session.commit()
    return {"deleted": result.rowcount}


@router.post("/notifications/delete")
def delete_notifications(
    request: MarkReadRequest,
    device: str,
    access_level: Annotated[AccessLevel, Depends(auth_dependency)] = AccessLevel.NONE,
    session: Session = Depends(get_session),
):
    """Delete a list of notification IDs for the device."""
    _require_owner(access_level)
    import uuid as _uuid
    ids = [_uuid.UUID(i) for i in request.ids]
    result = session.execute(
        sa_delete(Notification).where(
            Notification.id.in_(ids), Notification.device == device
        )
    )
    session.commit()
    return {"deleted": result.rowcount}


# ---------------------------------------------------------------------------
# Web Push subscriptions
# ---------------------------------------------------------------------------
@router.get("/push/vapid-public-key")
def vapid_public_key():
    """Public applicationServerKey for the browser to subscribe with."""
    from services.push import VAPID_PUBLIC_KEY, push_enabled
    return {"publicKey": VAPID_PUBLIC_KEY, "enabled": push_enabled()}


@router.post("/push/subscribe")
def push_subscribe(
    sub: PushSubscriptionIn,
    device: str,
    access_level: Annotated[AccessLevel, Depends(auth_dependency)] = AccessLevel.NONE,
    session: Session = Depends(get_session),
):
    """Register (or refresh) a Web Push subscription for the device."""
    _require_owner(access_level)
    from sqlalchemy.dialects.postgresql import insert as pg_insert

    stmt = (
        pg_insert(PushSubscription)
        .values(
            device=device,
            endpoint=sub.endpoint,
            p256dh=sub.keys.p256dh,
            auth=sub.keys.auth,
        )
        .on_conflict_do_update(
            index_elements=["endpoint"],
            set_={"device": device, "p256dh": sub.keys.p256dh, "auth": sub.keys.auth},
        )
    )
    session.execute(stmt)
    session.commit()
    return {"ok": True}


@router.post("/push/test")
def push_test(
    device: str,
    access_level: Annotated[AccessLevel, Depends(auth_dependency)] = AccessLevel.NONE,
    session: Session = Depends(get_session),
):
    """Send a sample push to the device's browsers, to verify delivery."""
    _require_owner(access_level)
    from services.push import push_enabled, send_to_device

    if not push_enabled():
        return {"ok": False, "sent": 0, "reason": "push not configured on server"}

    sent = send_to_device(
        session,
        device,
        title="🔔 Test notification",
        body="If you can see (and feel) this, phone alerts are working.",
        tag="test",
    )
    return {"ok": sent > 0, "sent": sent}


@router.post("/push/unsubscribe")
def push_unsubscribe(
    body: PushUnsubscribeIn,
    access_level: Annotated[AccessLevel, Depends(auth_dependency)] = AccessLevel.NONE,
    session: Session = Depends(get_session),
):
    """Remove a Web Push subscription by endpoint."""
    _require_owner(access_level)
    session.execute(
        sa_delete(PushSubscription).where(PushSubscription.endpoint == body.endpoint)
    )
    session.commit()
    return {"ok": True}

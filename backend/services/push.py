"""
push.py — Web Push (VAPID) delivery to subscribed browsers.

Config via env:
  VAPID_PUBLIC_KEY   base64url applicationServerKey (handed to the browser)
  VAPID_PRIVATE_KEY  PEM private key (PKCS8), newlines may be \\n-escaped
  VAPID_SUBJECT      mailto:you@example.com  (contact for push services)

send_to_device() loads all subscriptions for a device and pushes the payload,
pruning subscriptions the push service reports as gone (404/410).
"""
from __future__ import annotations

import json
import logging
import os
from typing import Optional

from sqlalchemy import delete as sa_delete, select
from sqlalchemy.orm import Session

from database.models import PushSubscription

logger = logging.getLogger(__name__)

VAPID_PUBLIC_KEY = os.getenv("VAPID_PUBLIC_KEY", "")
_VAPID_PRIVATE_KEY = os.getenv("VAPID_PRIVATE_KEY", "").replace("\\n", "\n")
_VAPID_SUBJECT = os.getenv("VAPID_SUBJECT", "mailto:admin@lifelog-picam.local")


def push_enabled() -> bool:
    return bool(VAPID_PUBLIC_KEY and _VAPID_PRIVATE_KEY)


def send_to_device(
    session: Session,
    device: str,
    *,
    title: str,
    body: str = "",
    url: Optional[str] = None,
    tag: Optional[str] = None,
    icon: Optional[str] = None,
) -> int:
    """Push a notification to every subscription for `device`. Returns count sent."""
    if not push_enabled():
        logger.debug("Web push disabled (no VAPID keys); skipping.")
        return 0

    try:
        from pywebpush import WebPushException, webpush
    except ImportError:
        logger.warning("pywebpush not installed; cannot send web push.")
        return 0

    subs = session.execute(
        select(PushSubscription).where(PushSubscription.device == device)
    ).scalars().all()
    if not subs:
        return 0

    payload = json.dumps(
        {"title": title, "body": body, "url": url, "tag": tag, "icon": icon}
    )
    sent = 0
    dead: list[str] = []
    for sub in subs:
        try:
            webpush(
                subscription_info={
                    "endpoint": sub.endpoint,
                    "keys": {"p256dh": sub.p256dh, "auth": sub.auth},
                },
                data=payload,
                vapid_private_key=_VAPID_PRIVATE_KEY,
                vapid_claims={"sub": _VAPID_SUBJECT},
                ttl=86400,
            )
            sent += 1
        except WebPushException as e:
            status = getattr(e.response, "status_code", None)
            if status in (404, 410):
                dead.append(sub.endpoint)  # subscription expired/unsubscribed
            else:
                logger.warning("Web push failed for %s: %s", device, e)
        except Exception as e:  # noqa: BLE001
            logger.warning("Web push error for %s: %s", device, e)

    if dead:
        session.execute(
            sa_delete(PushSubscription).where(PushSubscription.endpoint.in_(dead))
        )
        session.commit()
        logger.info("Pruned %d dead push subscriptions for %s", len(dead), device)

    return sent

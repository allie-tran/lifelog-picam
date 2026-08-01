"""Integration tests for the /notify router (in-app notifications CRUD)."""
import itertools
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import func, select

from auth.types import AccessLevel
from database.models import Notification
from routers.notifications import router as notifications_router

pytestmark = pytest.mark.integration

# Each notification needs a distinct segment_id: (device, date, type) with a
# NULL segment_id is unique-constrained, so same-type rows would otherwise clash.
_seg = itertools.count(1)


@pytest.fixture
def client(make_client):
    return make_client(notifications_router, prefix="/notify")


def _add_notification(session, device="testcam", *, read=False, title="Hi", ts=None):
    n = Notification(
        device=device,
        date="2026-08-01",
        timestamp=ts if ts is not None else datetime.now(timezone.utc),
        read=read,
        type="test",
        title=title,
        segment_id=next(_seg),
    )
    session.add(n)
    session.flush()
    return n


def test_list_forbidden_without_owner_access(make_client):
    client = make_client(
        notifications_router, prefix="/notify", access=AccessLevel.NONE
    )
    r = client.get("/notify/notifications", params={"device": "testcam"})
    assert r.status_code == 403


def test_list_returns_newest_first(client, db_session):
    now = datetime.now(timezone.utc)
    _add_notification(db_session, title="old", ts=now - timedelta(hours=1))
    _add_notification(db_session, title="new", ts=now)

    r = client.get("/notify/notifications", params={"device": "testcam"})
    assert r.status_code == 200
    titles = [n["title"] for n in r.json()]
    assert titles == ["new", "old"]


def test_list_scoped_to_device(client, db_session):
    _add_notification(db_session, device="testcam", title="mine")
    _add_notification(db_session, device="other", title="theirs")

    r = client.get("/notify/notifications", params={"device": "testcam"})
    titles = [n["title"] for n in r.json()]
    assert titles == ["mine"]


def test_unread_only_filter(client, db_session):
    _add_notification(db_session, read=False, title="unread")
    _add_notification(db_session, read=True, title="already-read")

    r = client.get(
        "/notify/notifications",
        params={"device": "testcam", "unread_only": "true"},
    )
    titles = [n["title"] for n in r.json()]
    assert titles == ["unread"]


def test_unread_count(client, db_session):
    _add_notification(db_session, read=False)
    _add_notification(db_session, read=False)
    _add_notification(db_session, read=True)

    r = client.get("/notify/notifications/unread-count", params={"device": "testcam"})
    assert r.status_code == 200
    assert r.json() == {"count": 2}


def test_mark_read_persists(client, db_session):
    n = _add_notification(db_session, read=False)

    r = client.post(
        "/notify/notifications/mark-read",
        params={"device": "testcam"},
        json={"ids": [str(n.id)]},
    )
    assert r.status_code == 200
    assert r.json() == {"marked": 1}

    # Endpoint committed to a savepoint; the row is updated for this session.
    db_session.expire_all()
    refreshed = db_session.get(Notification, n.id)
    assert refreshed.read is True


def test_mark_all_read(client, db_session):
    _add_notification(db_session, read=False)
    _add_notification(db_session, read=False)

    r = client.post(
        "/notify/notifications/mark-all-read", params={"device": "testcam"}
    )
    assert r.status_code == 200

    remaining_unread = db_session.execute(
        select(func.count(Notification.id)).where(
            Notification.device == "testcam", Notification.read == False
        )
    ).scalar_one()
    assert remaining_unread == 0


def test_clear_all_deletes_only_that_device(client, db_session):
    _add_notification(db_session, device="testcam")
    _add_notification(db_session, device="testcam")
    _add_notification(db_session, device="other")

    r = client.post("/notify/notifications/clear-all", params={"device": "testcam"})
    assert r.status_code == 200
    assert r.json() == {"deleted": 2}

    remaining = db_session.execute(
        select(func.count(Notification.id))
    ).scalar_one()
    assert remaining == 1  # the "other" device's notification survives


def test_delete_specific_ids(client, db_session):
    keep = _add_notification(db_session, title="keep")
    drop = _add_notification(db_session, title="drop")

    r = client.post(
        "/notify/notifications/delete",
        params={"device": "testcam"},
        json={"ids": [str(drop.id)]},
    )
    assert r.status_code == 200
    assert r.json() == {"deleted": 1}

    remaining_ids = set(db_session.execute(select(Notification.id)).scalars().all())
    assert remaining_ids == {keep.id}

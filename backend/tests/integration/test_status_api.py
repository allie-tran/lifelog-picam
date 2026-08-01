"""Integration tests for the /status router against a real Postgres schema."""
import uuid
from datetime import datetime, timedelta, timezone

import pytest

from auth.types import AccessLevel
from database.models import Device, Image, SensorDevice
from routers.status import router as status_router

pytestmark = pytest.mark.integration


@pytest.fixture
def client(make_client):
    return make_client(status_router, prefix="/status")


def _seed_device_with_camera(session, device_id="testcam", *, last_seen=None):
    """Insert a content Device plus an associated camera SensorDevice, flushed
    (not committed) so the endpoint sees them within the test transaction."""
    device = Device(id=uuid.uuid4(), device_id=device_id)
    session.add(device)
    session.flush()
    session.add(SensorDevice(
        device_id=f"{device_id}-cam",
        device_nickname="Test Camera",
        sensor_type="camera",
        associated_user=device.id,
        last_seen=last_seen if last_seen is not None else datetime.now(timezone.utc),
    ))
    session.flush()
    return device


def test_health_needs_no_auth_or_db(client):
    r = client.get("/status/health")
    assert r.status_code == 200
    assert r.json() == {"status": "ok"}


def test_current_forbidden_without_access(make_client):
    client = make_client(status_router, prefix="/status", access=AccessLevel.NONE)
    r = client.get("/status/current", params={"device": "testcam"})
    assert r.status_code == 403


def test_current_unknown_device_returns_empty_status(client):
    r = client.get("/status/current", params={"device": "does-not-exist"})
    assert r.status_code == 200
    body = r.json()
    assert body["cameraOnline"] is False
    assert body["sensors"] == []
    assert body["currentActivity"] is None


def test_current_reports_online_camera(client, db_session):
    _seed_device_with_camera(db_session, "testcam")

    r = client.get("/status/current", params={"device": "testcam"})
    assert r.status_code == 200
    body = r.json()

    assert len(body["sensors"]) == 1
    sensor = body["sensors"][0]
    assert sensor["sensorType"] == "camera"
    assert sensor["online"] is True
    assert body["cameraOnline"] is True


def test_current_camera_offline_when_last_seen_is_stale(client, db_session):
    stale = datetime.now(timezone.utc) - timedelta(hours=1)
    _seed_device_with_camera(db_session, "testcam", last_seen=stale)

    r = client.get("/status/current", params={"device": "testcam"})
    body = r.json()
    assert body["sensors"][0]["online"] is False
    assert body["cameraOnline"] is False


def test_current_surfaces_latest_activity(client, db_session):
    device = _seed_device_with_camera(db_session, "testcam")
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    # Two images; the newer one carries the activity that should be reported.
    db_session.add(Image(
        image_path="testcam/older.jpg", device="testcam", device_ref_id=device.id,
        timestamp=now - timedelta(minutes=5), date="2026-08-01",
        activity="Walking", deleted=False,
    ))
    db_session.add(Image(
        image_path="testcam/newer.jpg", device="testcam", device_ref_id=device.id,
        timestamp=now, date="2026-08-01",
        activity="Coding", activity_description="Writing tests", deleted=False,
    ))
    db_session.flush()

    r = client.get("/status/current", params={"device": "testcam"})
    body = r.json()
    assert body["currentActivity"] == "Coding"
    assert body["currentActivityDescription"] == "Writing tests"


def test_current_ignores_deleted_images(client, db_session):
    device = _seed_device_with_camera(db_session, "testcam")
    db_session.add(Image(
        image_path="testcam/deleted.jpg", device="testcam", device_ref_id=device.id,
        timestamp=datetime.now(timezone.utc).replace(tzinfo=None), date="2026-08-01",
        activity="Coding", deleted=True,
    ))
    db_session.flush()

    r = client.get("/status/current", params={"device": "testcam"})
    # Deleted image must not become the "current" activity.
    assert r.json()["currentActivity"] is None

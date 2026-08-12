"""Integration tests for the /explore router (available-values queries)."""
from datetime import datetime, timezone

import pytest

from auth.types import AccessLevel
from database.models import Image
from routers.explore import router as explore_router

pytestmark = pytest.mark.integration


@pytest.fixture
def client(make_client):
    return make_client(explore_router, prefix="/explore")


def _add_image(session, *, device="testcam", path, year=None, local_ts=None, deleted=False):
    session.add(Image(
        image_path=path, device=device,
        timestamp=datetime.now(timezone.utc).replace(tzinfo=None),
        local_timestamp=local_ts, year=year, deleted=deleted,
    ))
    session.flush()


def test_health_needs_no_auth(client):
    r = client.get("/explore/health")
    assert r.status_code == 200
    assert r.json() == {"status": "ok"}


def test_available_values_forbidden_without_owner(make_client):
    client = make_client(explore_router, prefix="/explore", access=AccessLevel.NONE)
    r = client.post(
        "/explore/available-values",
        params={"device": "testcam"},
        json={"field": "year"},
    )
    assert r.status_code == 403


def test_available_values_invalid_field_returns_400(client):
    r = client.post(
        "/explore/available-values",
        params={"device": "testcam"},
        json={"field": "not-a-field"},
    )
    assert r.status_code == 400


def test_available_values_distinct_years(client, db_session):
    _add_image(db_session, path="a.jpg", year=2025)
    _add_image(db_session, path="b.jpg", year=2025)
    _add_image(db_session, path="c.jpg", year=2026)
    _add_image(db_session, path="other.jpg", device="other", year=2000)

    r = client.post(
        "/explore/available-values",
        params={"device": "testcam"},
        json={"field": "year"},
    )
    assert r.status_code == 200
    assert sorted(r.json()) == [2025, 2026]  # distinct, device-scoped


def test_available_values_dates_exclude_deleted(client, db_session):
    _add_image(
        db_session, path="live.jpg",
        local_ts=datetime(2026, 8, 1, 12, tzinfo=timezone.utc),
    )
    _add_image(
        db_session, path="gone.jpg", deleted=True,
        local_ts=datetime(2026, 8, 2, 12, tzinfo=timezone.utc),
    )

    r = client.post(
        "/explore/available-values",
        params={"device": "testcam"},
        json={"field": "date"},
    )
    assert r.status_code == 200
    assert r.json() == ["2026-08-01"]  # deleted row excluded

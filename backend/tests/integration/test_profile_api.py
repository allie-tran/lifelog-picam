"""Integration tests for the /profile router (per-device meal times)."""
import pytest
from sqlalchemy import select

from auth.types import AccessLevel
from database.models import MealProfile
from routers.profile import router as profile_router

pytestmark = pytest.mark.integration


@pytest.fixture
def client(make_client):
    return make_client(profile_router, prefix="/profile")


def _add_meal(session, device="testcam", *, meal="lunch", minute=720, auto=True):
    m = MealProfile(
        device=device, meal=meal, usual_minute=minute,
        grace_minute=90, enabled=True, auto=auto,
    )
    session.add(m)
    session.flush()
    return m


def test_get_forbidden_without_owner_access(make_client):
    client = make_client(profile_router, prefix="/profile", access=AccessLevel.NONE)
    r = client.get("/profile/meal-times", params={"device": "testcam"})
    assert r.status_code == 403


def test_get_returns_meals_sorted_by_time(client, db_session):
    _add_meal(db_session, meal="dinner", minute=1200)
    _add_meal(db_session, meal="breakfast", minute=480)
    _add_meal(db_session, meal="lunch", minute=720)

    r = client.get("/profile/meal-times", params={"device": "testcam"})
    assert r.status_code == 200
    assert [m["meal"] for m in r.json()] == ["breakfast", "lunch", "dinner"]


def test_get_scoped_to_device(client, db_session):
    _add_meal(db_session, device="testcam", meal="lunch")
    _add_meal(db_session, device="other", meal="dinner")

    r = client.get("/profile/meal-times", params={"device": "testcam"})
    assert [m["meal"] for m in r.json()] == ["lunch"]


def test_put_rejects_invalid_meal(client):
    r = client.put(
        "/profile/meal-times",
        params={"device": "testcam"},
        json={"meal": "brunch", "usualMinute": 600},
    )
    assert r.status_code == 200
    assert "error" in r.json()


def test_put_inserts_manual_meal(client, db_session):
    r = client.put(
        "/profile/meal-times",
        params={"device": "testcam"},
        json={"meal": "Dinner", "usualMinute": 1230},
    )
    assert r.status_code == 200
    assert r.json() == {"ok": True, "meal": "dinner"}

    db_session.expire_all()
    row = db_session.execute(
        select(MealProfile).where(MealProfile.device == "testcam")
    ).scalar_one()
    assert row.meal == "dinner"
    assert row.usual_minute == 1230
    assert row.auto is False  # manual override


def test_put_clamps_minute_into_range(client, db_session):
    client.put(
        "/profile/meal-times",
        params={"device": "testcam"},
        json={"meal": "lunch", "usualMinute": 99999},
    )
    db_session.expire_all()
    row = db_session.execute(
        select(MealProfile).where(MealProfile.device == "testcam")
    ).scalar_one()
    assert row.usual_minute == 1439


def test_put_upserts_on_conflict(client, db_session):
    _add_meal(db_session, meal="lunch", minute=720, auto=True)

    client.put(
        "/profile/meal-times",
        params={"device": "testcam"},
        json={"meal": "lunch", "usualMinute": 800},
    )
    db_session.expire_all()
    rows = db_session.execute(
        select(MealProfile).where(
            MealProfile.device == "testcam", MealProfile.meal == "lunch"
        )
    ).scalars().all()
    assert len(rows) == 1  # updated, not duplicated
    assert rows[0].usual_minute == 800
    assert rows[0].auto is False


def test_delete_removes_meal(client, db_session):
    _add_meal(db_session, meal="lunch")

    r = client.request(
        "DELETE",
        "/profile/meal-times",
        params={"device": "testcam", "meal": "lunch"},
    )
    assert r.status_code == 200

    db_session.expire_all()
    remaining = db_session.execute(
        select(MealProfile).where(MealProfile.device == "testcam")
    ).scalars().all()
    assert remaining == []

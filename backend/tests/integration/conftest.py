"""Fixtures for the API integration suite.

These tests exercise real FastAPI endpoints against a real PostgreSQL schema.
To avoid touching the live `picam` database we create a throwaway `picam_test`
database on the same server (same credentials, so pgvector + PostGIS are already
available), build the full ORM schema into it, and drop it at the end.

Each test runs inside a transaction that is rolled back, so tests don't see one
another's rows. Auth and the DB session are injected via FastAPI dependency
overrides, so no JWT/Redis session is required.

Run with:  pytest -m integration
"""
import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

TEST_DB = "picam_test"


def _server_base_url() -> str:
    """PG_URI with the database name stripped (…@host:port)."""
    from database import PG_URI
    return PG_URI.rpartition("/")[0]


@pytest.fixture(scope="session")
def test_engine():
    base = _server_base_url()

    # (Re)create the throwaway database from the maintenance DB in autocommit —
    # CREATE/DROP DATABASE can't run inside a transaction.
    admin = create_engine(f"{base}/postgres", isolation_level="AUTOCOMMIT")
    with admin.connect() as conn:
        conn.execute(text(f"DROP DATABASE IF EXISTS {TEST_DB} WITH (FORCE)"))
        conn.execute(text(f"CREATE DATABASE {TEST_DB}"))
    admin.dispose()

    engine = create_engine(f"{base}/{TEST_DB}")
    with engine.begin() as conn:
        conn.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))
        conn.execute(text("CREATE EXTENSION IF NOT EXISTS postgis"))

    # Import models only now, so their pgvector/PostGIS column types resolve
    # against a DB that has the extensions installed.
    from database.models import Base
    Base.metadata.create_all(engine)

    yield engine

    engine.dispose()
    admin = create_engine(f"{base}/postgres", isolation_level="AUTOCOMMIT")
    with admin.connect() as conn:
        conn.execute(text(f"DROP DATABASE IF EXISTS {TEST_DB} WITH (FORCE)"))
    admin.dispose()


@pytest.fixture
def db_session(test_engine):
    """A session wrapped in an outer transaction that is always rolled back, so
    tests stay isolated even from one another's writes.

    `join_transaction_mode="create_savepoint"` makes the endpoint's own
    `session.commit()` land on a SAVEPOINT instead of the real transaction, so
    committing endpoints (notifications, etc.) still can't escape the rollback.
    Seeded rows are visible to the endpoint because it shares this same session
    via the `get_session` override.
    """
    conn = test_engine.connect()
    trans = conn.begin()
    session = sessionmaker(
        bind=conn, join_transaction_mode="create_savepoint"
    )()
    try:
        yield session
    finally:
        session.close()
        trans.rollback()
        conn.close()


@pytest.fixture
def make_client(db_session):
    """Factory: build a TestClient for a bare app mounting the given router,
    with `get_session` and `auth_dependency` overridden.

    `access` sets the AccessLevel that `auth_dependency` resolves to, so tests
    can drive both the authorized and forbidden paths without real tokens.
    """
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from auth.auth_models import auth_dependency
    from auth.types import AccessLevel
    from database import get_session

    def _make(router, prefix="", access=AccessLevel.ADMIN):
        app = FastAPI()
        app.include_router(router, prefix=prefix)
        app.dependency_overrides[get_session] = lambda: db_session
        app.dependency_overrides[auth_dependency] = lambda: access
        return TestClient(app)

    return _make

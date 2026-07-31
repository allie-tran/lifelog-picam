from mongodb_odm import connect, disconnect
from sqlalchemy import create_engine
# from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy.orm import sessionmaker
from dotenv import load_dotenv
import os

# Load backend/.env by absolute path before reading any config. The engine is
# built at import time, so a celery worker started from a different CWD (where a
# bare load_dotenv() can't find .env) would otherwise fall back to the default
# postgres:password and fail auth. Path is relative to this file, not the CWD.
load_dotenv(os.path.join(os.path.dirname(__file__), os.pardir, ".env"))

PG_URI = os.getenv("PG_URI", "postgresql://postgres:password@localhost:5432/picam")
ASYNC_PG_URI = os.getenv("ASYNC_PG_URI", "postgresql+asyncpg://postgres:password@localhost:5432/picam")

# --- Synchronous SQLAlchemy Engine with Timeouts ---
engine = create_engine(
    PG_URI,
    # 1. Pool timeouts
    pool_timeout=30,  # seconds to wait for a connection from the pool
    pool_recycle=1800,  # seconds to recycle a connection (to prevent stale connections)

    # 2. Driver/Socket timeouts
    connect_args={
        "options": "-c statement_timeout=10000", # abort queries that run longer than 10 seconds
        "connect_timeout": 10,  # seconds to wait for a connection to be established
    },
)

# # --- Asynchronous SQLAlchemy Engine with Timeouts ---
# async_engine = create_async_engine(
#     ASYNC_PG_URI,
#     pool_timeout=30,  # seconds to wait for a connection from the pool
#     pool_recycle=1800,  # seconds to recycle a connection (to prevent stale connections)
#     connect_args={
#         "timeout": 10,  # seconds to wait for a connection to be established
#         "command_timeout": 10,  # seconds to wait for a command to complete
#     },
# )

SessionLocal = sessionmaker(bind=engine)

def get_session():
    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()

def close_db():
    engine.dispose()
    disconnect()

def init_db():
    connect("mongodb://localhost:27017/picam")

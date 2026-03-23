from mongodb_odm import connect
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
import os

PG_URI = os.getenv("PG_URI", "postgresql://postgres:password@localhost:5432/picam")

engine = create_engine(PG_URI)
SessionLocal = sessionmaker(bind=engine)


def get_session():
    with SessionLocal() as session:
        yield session


def init_db():
    connect("mongodb://localhost:27017/picam")

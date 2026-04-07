"""
models.py — SQLAlchemy ORM models for KatoAI PostgreSQL schema
Requires: sqlalchemy, pgvector, geoalchemy2
  pip install sqlalchemy psycopg[binary] pgvector geoalchemy2
"""

import uuid
from sqlalchemy import (
    Column,
    Boolean,
    Integer,
    Float,
    Text,
    DateTime,
    ForeignKey,
    UniqueConstraint,
    LargeBinary,
)
from sqlalchemy.dialects.postgresql import UUID, JSONB
from sqlalchemy.orm import DeclarativeBase, relationship
from pgvector.sqlalchemy import Vector
from geoalchemy2 import Geography


class Base(DeclarativeBase):
    pass


# ---------------------------------------------------------------------------
# Location
# ---------------------------------------------------------------------------

class Location(Base):
    __tablename__ = "locations"

    key = Column(Text, nullable=False, unique=True)
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name = Column(Text)
    country = Column(Text)

    fsq_id = Column(Text, nullable=True)
    info = Column(Text)
    stop = Column(Boolean)


    timezone = Column(Text)
    address = Column(Text)
    images = relationship("Image", back_populates="location")


# ---------------------------------------------------------------------------
# Device + whitelist
# ---------------------------------------------------------------------------


class DeviceSecret(Base):
    """
    Isolated table for sensitive device data.
    Grant SELECT on this table only to the device-facing service role,
    NOT to the general API role.

    SQL to restrict access:
        REVOKE ALL ON device_secrets FROM api_role;
        GRANT SELECT ON device_secrets TO device_role;
    """

    __tablename__ = "device_secrets"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    device_id = Column(
        UUID(as_uuid=True),
        ForeignKey("devices.id", ondelete="CASCADE"),
        unique=True,
        nullable=False,
    )
    transform_matrix = Column(LargeBinary, nullable=True)

    device = relationship("Device", back_populates="secret")


class Device(Base):
    __tablename__ = "devices"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    mongo_id = Column(Text, unique=True, nullable=True)
    device_id = Column(Text, unique=True, nullable=False)
    last_seen = Column(DateTime(timezone=True), nullable=True)
    public_key = Column(Text, nullable=True)
    whitelist = relationship(
        "DeviceWhitelistEntry", back_populates="device", cascade="all, delete-orphan"
    )
    images = relationship("Image", back_populates="device_ref")
    secret = relationship(
        "DeviceSecret",
        back_populates="device",
        uselist=False,
        cascade="all, delete-orphan",
    )


class DeviceWhitelistEntry(Base):
    """One row per named person per device."""

    __tablename__ = "device_whitelist"
    __table_args__ = (
        UniqueConstraint("device_id", "name", name="uq_whitelist_device_name"),
    )

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    device_id = Column(
        UUID(as_uuid=True), ForeignKey("devices.id", ondelete="CASCADE"), nullable=False
    )
    name = Column(Text, nullable=False)
    cropped = Column(JSONB)  # list of image path strings

    device = relationship("Device", back_populates="whitelist")
    embeddings = relationship(
        "DeviceWhitelistEmbedding", back_populates="entry", cascade="all, delete-orphan"
    )


class DeviceWhitelistEmbedding(Base):
    """One row per embedding vector per whitelist entry."""

    __tablename__ = "device_whitelist_embeddings"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    entry_id = Column(
        UUID(as_uuid=True),
        ForeignKey("device_whitelist.id", ondelete="CASCADE"),
        nullable=False,
    )
    embedding = Column(Vector(512), nullable=False)

    entry = relationship("DeviceWhitelistEntry", back_populates="embeddings")


# ---------------------------------------------------------------------------
# Image
# ---------------------------------------------------------------------------


class Image(Base):
    __tablename__ = "images"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    mongo_id = Column(Text, unique=True, nullable=True)

    # File
    image_path = Column(Text, nullable=False)
    thumbnail = Column(Text, nullable=False)
    is_video = Column(Boolean, nullable=False, default=False)

    # Time
    timestamp = Column(DateTime(timezone=False))  # stored in UTC, no timezone info
    local_timestamp = Column(
        DateTime(timezone=True)
    )  # stored with timezone info, for display

    # Time from local_timestamp
    date = Column(Text)
    year = Column(Integer)
    month = Column(Integer)
    day = Column(Integer)
    hour = Column(Integer)
    seconds_from_midnight = Column(Integer)

    # Device / segment
    device = Column(Text)  # raw string from MongoDB, used during migration
    device_ref_id = Column(UUID(as_uuid=True), ForeignKey("devices.id"), nullable=True)
    segment_id = Column(Integer)

    # Location FK
    location_id = Column(UUID(as_uuid=True), ForeignKey("locations.id"), nullable=True)

    # Activity
    activity = Column(Text)
    activity_confidence = Column(Text)
    activity_description = Column(Text)

    # Soft delete
    deleted = Column(Boolean, default=False)
    deleted_time = Column(DateTime(timezone=True), nullable=True)
    new = Column(Boolean, default=False)

    # Processing flags
    proc_encoded = Column(Boolean, default=False)
    proc_yolo = Column(Boolean, default=False)
    proc_ocr = Column(Boolean, default=False)
    proc_deepface = Column(Boolean, default=False)
    proc_insightface = Column(Boolean, default=False)
    proc_face_recognition = Column(Boolean, default=False)
    proc_sam3 = Column(Boolean, default=False)

    # Relationships
    location = relationship("Location", back_populates="images")
    device_ref = relationship("Device", back_populates="images")
    gps = relationship(
        "ImageGPS", back_populates="image", uselist=False, cascade="all, delete-orphan"
    )
    people = relationship(
        "ImagePerson", back_populates="image", cascade="all, delete-orphan"
    )
    objects = relationship(
        "ImageObject", back_populates="image", cascade="all, delete-orphan"
    )
    ocr = relationship("ImageOCR", back_populates="image", cascade="all, delete-orphan")


# ---------------------------------------------------------------------------
# Embedding
# ---------------------------------------------------------------------------


class ImageEmbedding(Base):
    __tablename__ = "image_embedding"

    image_id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    embedding = Column(Vector(768), nullable=False)


# ---------------------------------------------------------------------------
# GPS — PostGIS Geography for real-world spatial queries
# ---------------------------------------------------------------------------


class ImageGPS(Base):
    __tablename__ = "image_gps"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    image_id = Column(
        UUID(as_uuid=True),
        ForeignKey("images.id", ondelete="CASCADE"),
        nullable=False,
        unique=True,
    )

    # Raw scalars kept for debugging / display
    latitude = Column(Float, nullable=False)
    longitude = Column(Float, nullable=False)
    elevation = Column(Float)
    timestamp = Column(Float)
    formatted_time = Column(Text)
    satellites = Column(Integer)
    source = Column(Text)
    gap_s = Column(Float)
    interpolated = Column(Boolean, default=False)
    timezone = Column(Text)

    # PostGIS Geography — distances in metres, no projection math needed.
    # Populated as: ST_MakePoint(longitude, latitude)  ← lon first in WGS84
    # Spatial index created in migrate.py after bulk load.
    geog = Column(Geography(geometry_type="POINT", srid=4326), nullable=True)

    image = relationship("Image", back_populates="gps")


# ---------------------------------------------------------------------------
# People detections
# ---------------------------------------------------------------------------


class ImagePerson(Base):
    __tablename__ = "image_people"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    image_id = Column(
        UUID(as_uuid=True), ForeignKey("images.id", ondelete="CASCADE"), nullable=False
    )

    label = Column(Text)
    confidence = Column(Float)
    bbox = Column(JSONB)  # [x1, y1, x2, y2]
    cluster_label = Column(Integer, nullable=True)
    embedding = Column(Vector(512), nullable=True)

    image = relationship("Image", back_populates="people")


# ---------------------------------------------------------------------------
# YOLO object detections
# ---------------------------------------------------------------------------


class ImageObject(Base):
    __tablename__ = "image_objects"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    image_id = Column(
        UUID(as_uuid=True), ForeignKey("images.id", ondelete="CASCADE"), nullable=False
    )

    label = Column(Text)
    confidence = Column(Float)
    bbox = Column(JSONB)  # [x1, y1, x2, y2]

    image = relationship("Image", back_populates="objects")


# ---------------------------------------------------------------------------
# OCR results
# ---------------------------------------------------------------------------


class ImageOCR(Base):
    __tablename__ = "image_ocr"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    image_id = Column(
        UUID(as_uuid=True), ForeignKey("images.id", ondelete="CASCADE"), nullable=False
    )

    text = Column(Text)
    confidence = Column(Float)
    box_2d = Column(JSONB)  # [x1, y1, x2, y2]
    polygon = Column(JSONB)  # [[x,y], ...]

    image = relationship("Image", back_populates="ocr")

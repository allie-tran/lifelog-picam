"""
models.py — SQLAlchemy ORM models for KatoAI PostgreSQL schema
"""

from enum import StrEnum
import uuid

from geoalchemy2 import Geography
from pgvector.sqlalchemy import Vector
from sqlalchemy import (
    Boolean,
    Column,
    DateTime,
    Enum,
    Float,
    ForeignKey,
    Index,
    Integer,
    LargeBinary,
    Text,
    UniqueConstraint,
    func,
    literal_column,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import DeclarativeBase, relationship


class Base(DeclarativeBase):
    pass


# ---------------------------------------------------------------------------
# Location
# ---------------------------------------------------------------------------


class Location(Base):
    __tablename__ = "locations"
    __table_args__ = (
        # Performance indexes for your manual deduplication and searching
        Index("ix_locations_key", "key"),
        Index("ix_locations_fsq_id", "fsq_id"),
        Index("ix_locations_name_country", "name", "country"),
        Index("ix_locations_stop", "stop"),
    )

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    key = Column(
        Text, nullable=False, unique=True
    )
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


class Device(Base):
    __tablename__ = "devices"
    __table_args__ = (Index("ix_devices_device_id", "device_id"),)

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


class DeviceSecret(Base):
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


class DeviceWhitelistEntry(Base):
    __tablename__ = "device_whitelist"
    __table_args__ = (
        UniqueConstraint("device_id", "name", name="uq_whitelist_device_name"),
        Index("ix_whitelist_device", "device_id"),
    )

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    device_id = Column(
        UUID(as_uuid=True), ForeignKey("devices.id", ondelete="CASCADE"), nullable=False
    )
    name = Column(Text, nullable=False)
    cropped = Column(JSONB)

    device = relationship("Device", back_populates="whitelist")
    embeddings = relationship(
        "DeviceWhitelistEmbedding", back_populates="entry", cascade="all, delete-orphan"
    )


class DeviceWhitelistEmbedding(Base):
    __tablename__ = "device_whitelist_embeddings"
    __table_args__ = (
        Index("ix_whitelist_emb_entry", "entry_id"),
        Index(
            "ix_whitelist_emb_hnsw",
            "embedding",
            postgresql_using="hnsw",
            postgresql_ops={"embedding": "vector_cosine_ops"},
        ),
    )

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
class EmbeddingBase(Base):
    __abstract__ = True

    image_id = Column(
        UUID(as_uuid=True), ForeignKey("images.id", ondelete="CASCADE"), primary_key=True
    )

# Now adding a new model takes only 3 lines of code!
class ImageEmbedding(EmbeddingBase):
    __tablename__ = "image_embedding"
    __table_args__ = (
        Index(
            "ix_image_embedding_hnsw",
            "embedding",
            postgresql_using="hnsw",
            postgresql_ops={"embedding": "vector_cosine_ops"},
        ),
    )
    embedding = Column(Vector(768), nullable=False)
    image= relationship("Image", back_populates="embedding", uselist=False)


class CLIPEmbedding(EmbeddingBase):
    __tablename__ = "clip_embedding"
    __table_args__ = (
        Index(
            "ix_clip_embedding_hnsw",
            "embedding",
            postgresql_using="hnsw",
            postgresql_ops={"embedding": "vector_cosine_ops"},
        ),
    )
    embedding: Column = Column(Vector(768), nullable=False)
    image= relationship("Image", back_populates="clip_embedding", uselist=False)

class Image(Base):
    __tablename__ = "images"
    __table_args__ = (
        Index("ix_images_timestamp", "timestamp"),
        Index("ix_images_date", "date"),
        Index("ix_images_segment", "segment_id"),
        Index("ix_images_location", "location_id"),
        Index("ix_images_path", "image_path"),
        Index("ix_images_device", "device"),
        Index("ix_images_device_ref", "device_ref_id"),
        Index("ix_images_deleted", "deleted"),
        Index("ix_images_deleted_time", "deleted_time"),
    )

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    mongo_id = Column(Text, unique=True, nullable=True)
    image_path = Column(Text, nullable=False)
    thumbnail = Column(Text, nullable=False)
    is_video = Column(Boolean, nullable=False, default=False)
    timestamp = Column(DateTime(timezone=False))
    local_timestamp = Column(DateTime(timezone=True))
    timezone = Column(Text)
    date = Column(Text)
    year = Column(Integer)
    month = Column(Integer)
    day = Column(Integer)
    hour = Column(Integer)
    seconds_from_midnight = Column(Integer)
    device = Column(Text)
    device_ref_id = Column(UUID(as_uuid=True), ForeignKey("devices.id"), nullable=True)
    segment_id = Column(Integer)
    location_id = Column(UUID(as_uuid=True), ForeignKey("locations.id"), nullable=True)
    activity = Column(Text)
    activity_confidence = Column(Text)
    activity_description = Column(Text)
    deleted = Column(Boolean, default=False)
    deleted_time = Column(DateTime(timezone=True), nullable=True)
    new = Column(Boolean, default=False)
    proc_encoded = Column(Boolean, default=False)
    proc_yolo = Column(Boolean, default=False)
    proc_ocr = Column(Boolean, default=False)
    proc_deepface = Column(Boolean, default=False)
    proc_insightface = Column(Boolean, default=False)
    proc_face_recognition = Column(Boolean, default=False)
    proc_sam3 = Column(Boolean, default=False)

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

    embedding = relationship(
        "ImageEmbedding",
        back_populates="image",
        uselist=False, # This makes it 1:1
        cascade="all, delete-orphan"
    )

    clip_embedding = relationship(
        "CLIPEmbedding",
        back_populates="image",
        uselist=False, # This makes it 1:1
        cascade="all, delete-orphan"
    )

    def get_embedding(self, model_type="conclip"):
        """The 'Advanced' dynamic switcher."""
        if model_type == "vitl14@336":
            return self.clip_embedding
        return self.embedding

# ---------------------------------------------------------------------------
# GPS, People, Objects, OCR
# ---------------------------------------------------------------------------


class ImageGPS(Base):
    __tablename__ = "image_gps"
    __table_args__ = (
        Index("ix_gps_image", "image_id"),
        Index("ix_gps_geog", "geog", postgresql_using="gist"),
    )

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    image_id = Column(
        UUID(as_uuid=True),
        ForeignKey("images.id", ondelete="CASCADE"),
        nullable=False,
        unique=True,
    )
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
    geog = Column(Geography(geometry_type="POINT", srid=4326), nullable=True)

    image = relationship("Image", back_populates="gps")


class ImagePerson(Base):
    __tablename__ = "image_people"
    __table_args__ = (
        Index("ix_people_image", "image_id"),
        Index("ix_people_cluster", "cluster_label"),
        Index(
            "ix_people_embedding",
            "embedding",
            postgresql_using="hnsw",
            postgresql_ops={"embedding": "vector_cosine_ops"},
        ),
    )

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    image_id = Column(
        UUID(as_uuid=True), ForeignKey("images.id", ondelete="CASCADE"), nullable=False
    )
    label = Column(Text)
    confidence = Column(Float)
    bbox = Column(JSONB)
    cluster_label = Column(Integer, nullable=True)
    embedding = Column(Vector(512), nullable=True)

    image = relationship("Image", back_populates="people")


class ImageObject(Base):
    __tablename__ = "image_objects"
    __table_args__ = (
        Index("ix_objects_image", "image_id"),
        Index("ix_objects_label", "label"),
    )

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    image_id = Column(
        UUID(as_uuid=True), ForeignKey("images.id", ondelete="CASCADE"), nullable=False
    )
    label = Column(Text)
    confidence = Column(Float)
    bbox = Column(JSONB)

    image = relationship("Image", back_populates="objects")


class ImageOCR(Base):
    __tablename__ = "image_ocr"
    __table_args__ = (
        Index("ix_ocr_image", "image_id"),
        # Full Text Search Index
        Index(
            "ix_ocr_fts",
            func.to_tsvector(literal_column("'english'"), func.coalesce(Column("text"), '')),
            postgresql_using="gin",
        ),
    )

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    image_id = Column(
        UUID(as_uuid=True), ForeignKey("images.id", ondelete="CASCADE"), nullable=False
    )
    text = Column(Text)
    confidence = Column(Float)
    box_2d = Column(JSONB)
    polygon = Column(JSONB)

    image = relationship("Image", back_populates="ocr")

class AnnotationType(StrEnum):
    RECTANGLE = "rectangle"   # 2 points
    POLYGON = "polygon"       # n points, closed
    POLYLINE = "polyline"     # n points, open
    KEYPOINT = "keypoint"     # 1 point

class Annotation(Base):
    __tablename__ = "annotations"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    image_id = Column(
        UUID(as_uuid=True),
        ForeignKey("images.id", ondelete="CASCADE"),
        nullable=False,
    )
    anno_type = Column(
        Enum(AnnotationType), default=AnnotationType.POLYGON, nullable=False
    )
    points = Column(JSONB)
    label = Column(Text)

    timestamp = Column(DateTime(timezone=True), server_default=func.now())
    author = Column(Text)

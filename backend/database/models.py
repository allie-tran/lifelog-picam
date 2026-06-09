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
    text,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import DeclarativeBase, relationship

from typing import List, Optional
from sqlalchemy import String, Integer, Boolean, Float, BigInteger, ForeignKey, JSON
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


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
    key = Column(Text, nullable=False, unique=True)

    # Core identity
    name = Column(Text)          # POI name for stops; "City A → City B" for moves
    stop = Column(Boolean)       # True = stop, False = move

    # Admin hierarchy (from Nominatim)
    suburb = Column(Text, nullable=True)   # neighbourhood / suburb / district
    city = Column(Text, nullable=True)     # city / town / village
    region = Column(Text, nullable=True)   # state / province / county
    country = Column(Text)
    postcode = Column(Text, nullable=True)

    # Geocoder output
    address = Column(Text)                 # full Nominatim display_name
    timezone = Column(Text)
    latitude = Column(Float)
    longitude = Column(Float)

    # OSM provenance
    osm_type = Column(Text, nullable=True)     # node / way / relation
    osm_id = Column(Text, nullable=True)       # OSM element id

    # Wikidata enrichment
    wikidata_id = Column(Text, nullable=True)  # Wikidata QID (e.g. Q37158)
    description = Column(Text, nullable=True)  # Wikidata short description
    categories = Column(Text, nullable=True)   # semicolon-separated type list

    # Legacy — kept for backwards compatibility, no longer populated
    fsq_id = Column(Text, nullable=True)
    info = Column(Text, nullable=True)

    images = relationship("Image", back_populates="location")


# ---------------------------------------------------------------------------
# Device + whitelist
# ---------------------------------------------------------------------------


# These are Camera Device
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
# Sensors
# ---------------------------------------------------------------------------
class SensorDevice(Base):
    __tablename__ = "sensor_devices"
    __table_args__ = (Index("ix_sensor_devices_device_id", "device_id"),
                      Index("ix_sensor_devices_associated_user", "associated_user"),
                      UniqueConstraint("device_id", "sensor_type", name="uq_sensor_device_id_type"))

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    device_id = Column(Text, unique=False, nullable=False)
    device_nickname = Column(Text, nullable=True)
    secret = Column(Text, nullable=True)
    sensor_type = Column(Text, nullable=False)
    associated_user = Column(UUID(as_uuid=True), ForeignKey("devices.id", ondelete="SET NULL"), nullable=True)
    last_seen = Column(DateTime(timezone=True), nullable=True)

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
        # Composite indexes for the most common multi-column filter patterns
        Index("ix_images_device_date_deleted", "device", "date", "deleted"),
        Index("ix_images_device_deleted_time", "device", "deleted", "deleted_time"),
        # constraint: (device, image_path) should be unique to prevent duplicates from the same device
        UniqueConstraint("device", "image_path", name="uq_device_image_path"),
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
    activity_group = Column(Text, nullable=True)
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
    width = Column(Integer)
    height = Column(Integer)

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

    annotations = relationship(
        "Annotation", back_populates="image", cascade="all, delete-orphan"
    )

    def get_embedding(self, model_type="conclip"):
        """The 'Advanced' dynamic switcher."""
        if model_type == "vitl14@336":
            return self.clip_embedding
        return self.embedding

# ---------------------------------------------------------------------------
# GPS, People, Objects, OCR
# ---------------------------------------------------------------------------
class RawGPS(Base):
    __tablename__ = "raw_gps"
    __table_args__ = (
        Index("ix_raw_gps_device", "device_id"),
        Index("ix_raw_gps_time", "timestamp"),
        # device and timestamp should be unique to prevent duplicates from the same device at the same time
        UniqueConstraint("device_id", "timestamp", name="uq_raw_gps_device_time"),
    )

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    device_id = Column(
        UUID(as_uuid=True),
        ForeignKey("devices.id", ondelete="CASCADE"),
        nullable=False,
    )
    latitude = Column(Float, nullable=False)
    longitude = Column(Float, nullable=False)
    elevation = Column(Float)
    timestamp = Column(DateTime(timezone=False))
    timezone = Column(Text)


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

class PeopleCluster(Base):
    __tablename__ = "people_clusters"
    __table_args__ = (
        Index("ix_people_clusters_label", "cluster_label"),
    )

    id: Column[UUID] = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4, unique=True)
    cluster_label = Column(Text, nullable=False)
    center_embedding = Column(Vector(512), nullable=False)

    # The relationship to the people
    people = relationship("ImagePerson", back_populates="cluster")

class ImagePerson(Base):
    __tablename__ = "image_people"
    __table_args__ = (
        Index("ix_people_image", "image_id"),
        Index("ix_people_id", "id"),
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
    rel_bbox = Column(JSONB)
    embedding = Column(Vector(512), nullable=True)

    cluster_id = Column(
        UUID(as_uuid=True),
        ForeignKey("people_clusters.id", ondelete="SET NULL"),
        nullable=True,
    )

    image = relationship("Image", back_populates="people")
    cluster = relationship(
        "PeopleCluster",
        back_populates="people"
    )


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
    rel_bbox = Column(JSONB)

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
    image = relationship("Image", back_populates="annotations")


# ---------------------------------------------------------------------------
# Health Data

class HeartRateData(Base):
    __tablename__ = "bio_heart_rate"
    __table_args__ = (
        Index("ix_hr_device_time", "device_id", "time_stamp"),
        UniqueConstraint("device_id", "time_stamp", name="uq_hr_device_time")
    )
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    device_id: Mapped[str] = mapped_column(String(100))
    time_stamp: Mapped[int] = mapped_column(BigInteger, nullable=False)  # 18-digit ns


    contact_status: Mapped[bool] = mapped_column(Boolean)
    contact_status_supported: Mapped[bool] = mapped_column(Boolean)
    corrected_hr: Mapped[int] = mapped_column(Integer)
    hr: Mapped[int] = mapped_column(Integer)
    ppg_quality: Mapped[int] = mapped_column(Integer)
    rr_available: Mapped[bool] = mapped_column(Boolean)
    # Using JSON column for lists guarantees cross-compatibility (SQLite/Postgres)
    rrs_ms: Mapped[list] = mapped_column(JSON, default=list)

    __mapper_args__ = {"polymorphic_identity": "HR"}


class MagnetometerData(Base):
    __tablename__ = "bio_magnetometer"
    __table_args__ = (
        Index("ix_mag_device_time", "device_id", "time_stamp"),
        UniqueConstraint("device_id", "time_stamp", name="uq_mag_device_time")
    )
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    device_id: Mapped[str] = mapped_column(String(100))
    time_stamp: Mapped[int] = mapped_column(BigInteger, nullable=False)  # 18-digit ns


    x: Mapped[float] = mapped_column(Float)
    y: Mapped[float] = mapped_column(Float)
    z: Mapped[float] = mapped_column(Float)

    __mapper_args__ = {"polymorphic_identity": "MAGNETOMETER"}


class AccelerometerData(Base):
    __tablename__ = "bio_accelerometer"
    __table_args__ = (
        Index("ix_acc_device_time", "device_id", "time_stamp"),
        UniqueConstraint("device_id", "time_stamp", name="uq_acc_device_time")
    )
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    device_id: Mapped[str] = mapped_column(String(100))
    time_stamp: Mapped[int] = mapped_column(BigInteger, nullable=False)  # 18-digit ns


    x: Mapped[float] = mapped_column(Float)
    y: Mapped[float] = mapped_column(Float)
    z: Mapped[float] = mapped_column(Float)

    __mapper_args__ = {"polymorphic_identity": "ACC"}


class GyroscopeData(Base):
    __tablename__ = "bio_gyroscope"
    __table_args__ = (
        Index("ix_gyro_device_time", "device_id", "time_stamp"),
        UniqueConstraint("device_id", "time_stamp", name="uq_gyro_device_time")
    )
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    device_id: Mapped[str] = mapped_column(String(100))
    time_stamp: Mapped[int] = mapped_column(BigInteger, nullable=False)  # 18-digit ns


    x: Mapped[float] = mapped_column(Float)
    y: Mapped[float] = mapped_column(Float)
    z: Mapped[float] = mapped_column(Float)

    __mapper_args__ = {"polymorphic_identity": "GYRO"}


class PPGData(Base):
    __tablename__ = "bio_ppg"
    __table_args__ = (
        Index("ix_ppg_device_time", "device_id", "time_stamp"),
        UniqueConstraint("device_id", "time_stamp", name="uq_ppg_device_time")
    )
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    device_id: Mapped[str] = mapped_column(String(100))
    time_stamp: Mapped[int] = mapped_column(BigInteger, nullable=False)  # 18-digit ns


    channel_samples: Mapped[list] = mapped_column(JSON, default=list)
    status_bits: Mapped[list] = mapped_column(JSON, default=list)

    __mapper_args__ = {"polymorphic_identity": "PPG"}


class PPIData(Base):
    __tablename__ = "bio_ppi"
    __table_args__ = (
        Index("ix_ppi_device_time", "device_id", "time_stamp"),
    )
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    device_id: Mapped[str] = mapped_column(String(100))
    time_stamp: Mapped[int] = mapped_column(BigInteger, nullable=False)  # 18-digit ns


    blocker_bit: Mapped[bool] = mapped_column(Boolean)
    error_estimate: Mapped[int] = mapped_column(Integer)
    hr: Mapped[int] = mapped_column(Integer)
    ppi: Mapped[int] = mapped_column(Integer)
    skin_contact_status: Mapped[bool] = mapped_column(Boolean)
    skin_contact_supported: Mapped[bool] = mapped_column(Boolean)

    __mapper_args__ = {"polymorphic_identity": "PPI"}

class SkinTemperatureData(Base):
    __tablename__ = "bio_skin_temperature"
    __table_args__ = (
        Index("ix_skin_temp_device_time", "device_id", "time_stamp"),
        UniqueConstraint("device_id", "time_stamp", name="uq_skin_temp_device_time")
    )
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    device_id: Mapped[str] = mapped_column(String(100))
    time_stamp: Mapped[int] = mapped_column(BigInteger, nullable=False)  # 18-digit ns

    temperature: Mapped[float] = mapped_column(Float)


class Notification(Base):
    """
    In-app notifications generated by the pipeline (new location, unusual
    activity, novelty highlight, etc.).  Read by the mobile app via polling.
    """
    __tablename__ = "notifications"
    __table_args__ = (
        Index("ix_notif_device_date", "device", "date"),
        Index("ix_notif_device_read", "device", "read"),
        # Two partial unique indexes handle the NULL-segment_id case correctly.
        # PostgreSQL never considers two NULLs equal in a regular unique constraint,
        # so day-level notifications (segment_id IS NULL) need their own index.
        Index(
            "uq_notif_with_segment", "device", "date", "segment_id", "type",
            unique=True,
            postgresql_where=text("segment_id IS NOT NULL"),
        ),
        Index(
            "uq_notif_no_segment", "device", "date", "type",
            unique=True,
            postgresql_where=text("segment_id IS NULL"),
        ),
    )

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    device = Column(Text, nullable=False)
    date = Column(Text, nullable=False)   # YYYY-MM-DD
    timestamp = Column(DateTime(timezone=True), default=lambda: __import__('datetime').datetime.now(__import__('datetime').timezone.utc))
    read = Column(Boolean, default=False, nullable=False)
    type = Column(Text, nullable=False)   # new_location | unusual_activity | day_complete | novelty
    title = Column(Text, nullable=False)
    body = Column(Text, nullable=True)
    image_path = Column(Text, nullable=True)   # representative thumbnail
    segment_id = Column(Integer, nullable=True)
    extra = Column(JSONB, nullable=True)       # extra metadata


class BioDayStats(Base):
    """Per-day biometric aggregates, computed by the nightly Celery task."""
    __tablename__ = "bio_day_stats"
    __table_args__ = (
        Index("ix_bio_day_stats_device_date", "device_id", "date"),
        UniqueConstraint("device_id", "date", name="uq_bio_day_stats_device_date"),
    )

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    device_id: Mapped[str] = mapped_column(String(100), nullable=False)
    date: Mapped[str] = mapped_column(String(10), nullable=False)  # YYYY-MM-DD
    avg_hr: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    resting_hr: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    max_hr: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    rmssd: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    step_count: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    sleep_start = Column(DateTime, nullable=True)
    sleep_end = Column(DateTime, nullable=True)
    sleep_minutes: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    computed_at = Column(DateTime, nullable=True)


# Updated mapping pointing directly to the SQLalchemy Entities
db_type_mapping = {
    "PPG": PPGData,
    "ACC": AccelerometerData,
    "HR": HeartRateData,
    "MAGNETOMETER": MagnetometerData,
    "GYRO": GyroscopeData,
    "PPI": PPIData,
    "SKIN_TEMPERATURE": SkinTemperatureData,
}

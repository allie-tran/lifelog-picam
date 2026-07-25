"""
models.py — SQLAlchemy ORM models for KatoAI PostgreSQL schema
"""

from datetime import datetime, timezone
from enum import StrEnum
import uuid
from typing import Any, Optional

from geoalchemy2 import Geography
from pgvector.sqlalchemy import Vector
from sqlalchemy import (
    BigInteger,
    Boolean,
    Column,  # retained for FTS index expression in ImageOCR.__table_args__
    DateTime,
    Enum,
    Float,
    ForeignKey,
    Index,
    Integer,
    JSON,
    LargeBinary,
    String,
    Text,
    UniqueConstraint,
    func,
    literal_column,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    pass


# ---------------------------------------------------------------------------
# Location
# ---------------------------------------------------------------------------


class Location(Base):
    __tablename__ = "locations"
    __table_args__ = (
        Index("ix_locations_key", "key"),
        Index("ix_locations_fsq_id", "fsq_id"),
        Index("ix_locations_name_country", "name", "country"),
        Index("ix_locations_stop", "stop"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    key: Mapped[str] = mapped_column(Text, nullable=False, unique=True)

    # Core identity
    name: Mapped[str | None] = mapped_column(Text)           # POI name for stops; "City A → City B" for moves
    stop: Mapped[bool | None] = mapped_column(Boolean)       # True = stop, False = move

    # Admin hierarchy (from Nominatim)
    suburb: Mapped[str | None] = mapped_column(Text)
    city: Mapped[str | None] = mapped_column(Text)
    region: Mapped[str | None] = mapped_column(Text)
    country: Mapped[str | None] = mapped_column(Text)
    postcode: Mapped[str | None] = mapped_column(Text)

    # Geocoder output
    address: Mapped[str | None] = mapped_column(Text)        # full Nominatim display_name
    timezone: Mapped[str | None] = mapped_column(Text)
    latitude: Mapped[float | None] = mapped_column(Float)
    longitude: Mapped[float | None] = mapped_column(Float)

    # OSM provenance
    osm_type: Mapped[str | None] = mapped_column(Text)       # node / way / relation
    osm_id: Mapped[str | None] = mapped_column(Text)         # OSM element id

    # Wikidata enrichment
    wikidata_id: Mapped[str | None] = mapped_column(Text)    # Wikidata QID (e.g. Q37158)
    description: Mapped[str | None] = mapped_column(Text)    # Wikidata short description
    categories: Mapped[str | None] = mapped_column(Text)     # semicolon-separated type list

    # Set when the user corrects the venue via chat (stop_correction). The GPS
    # pipeline must NOT re-resolve / overwrite a stop pinned to this Location.
    user_confirmed: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=text("false"), default=False
    )

    # Legacy — kept for backwards compatibility, no longer populated
    fsq_id: Mapped[str | None] = mapped_column(Text)
    info: Mapped[str | None] = mapped_column(Text)

    images = relationship("Image", back_populates="location")
    labels = relationship("LocationLabel", back_populates="location", cascade="all, delete-orphan")


class OSMPoi(Base):
    """
    Offline gazetteer of named OSM points-of-interest (shops, cafes, amenities),
    imported from a Geofabrik extract via ``batch/import_osm_pois.py``.

    Live geocoders are unreliable for the "which of several adjacent venues was
    I in" question — Overpass is frequently down and Foursquare is unwanted, so
    candidates are served from this local table (same offline strategy as
    ``location/airports.py``). ``location/poi_gazetteer.nearby_pois`` queries it
    by ``geog`` radius; the stop's visual vector then disambiguates the
    candidates so a GPS centroid drifting onto the shop next door is corrected.
    """
    __tablename__ = "osm_pois"
    __table_args__ = (
        Index("ix_osm_pois_geog", "geog", postgresql_using="gist"),
        UniqueConstraint("osm_type", "osm_id", name="uq_osm_pois_element"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    osm_type: Mapped[str] = mapped_column(Text, nullable=False)   # node / way / relation
    osm_id: Mapped[str] = mapped_column(Text, nullable=False)     # OSM element id
    name: Mapped[str] = mapped_column(Text, nullable=False)
    category: Mapped[str | None] = mapped_column(Text)            # human type, e.g. "cafe", "supermarket"
    wikidata_id: Mapped[str | None] = mapped_column(Text)         # OSM wikidata=* tag, if present
    latitude: Mapped[float] = mapped_column(Float, nullable=False)
    longitude: Mapped[float] = mapped_column(Float, nullable=False)
    country: Mapped[str | None] = mapped_column(Text)            # ISO code, for region-scoped imports
    # spatial_index=False: the GIST index is declared explicitly above (and in
    # the migration) so geoalchemy2's listener doesn't add a second one.
    geog: Mapped[Any] = mapped_column(
        Geography(geometry_type="POINT", srid=4326, spatial_index=False), nullable=False
    )


class OSMTile(Base):
    """
    Coverage ledger for the lazily-filled ``osm_pois`` gazetteer.

    The pipeline populates POIs on demand: the first stop in a grid cell triggers
    one Overpass fetch for that cell, whose result is cached into ``osm_pois``.
    A row here marks the cell as fetched so later stops reuse the cache instead
    of re-querying Overpass. ``status='failed'`` rows are re-attempted (Overpass
    is flaky); ``status='ok'`` rows are refreshed only once stale.
    """
    __tablename__ = "osm_tiles"

    tile_lat: Mapped[float] = mapped_column(Float, primary_key=True)   # grid-floored
    tile_lon: Mapped[float] = mapped_column(Float, primary_key=True)
    fetched_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    status: Mapped[str | None] = mapped_column(Text)                  # 'ok' | 'failed'


class LocationLabel(Base):
    """Per-user label for a location (e.g. Home / Work). Keyed by Mongo username."""
    __tablename__ = "location_labels"
    __table_args__ = (
        UniqueConstraint("username", "location_id", name="uq_location_label_user_loc"),
        Index("ix_location_labels_username", "username"),
        Index("ix_location_labels_location", "location_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    username: Mapped[str] = mapped_column(Text, nullable=False)
    location_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("locations.id", ondelete="CASCADE"), nullable=False
    )
    label: Mapped[str] = mapped_column(Text, nullable=False)
    label_kind: Mapped[str] = mapped_column(Text, nullable=False, default="other")  # home / work / other

    location = relationship("Location", back_populates="labels")


# ---------------------------------------------------------------------------
# Device + whitelist
# ---------------------------------------------------------------------------


class Device(Base):
    __tablename__ = "devices"
    __table_args__ = (Index("ix_devices_device_id", "device_id"),)

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    mongo_id: Mapped[str | None] = mapped_column(Text, unique=True)
    device_id: Mapped[str] = mapped_column(Text, unique=True, nullable=False)
    last_seen: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    public_key: Mapped[str | None] = mapped_column(Text)
    keep_face_recognition: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)

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

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    device_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("devices.id", ondelete="CASCADE"),
        unique=True,
        nullable=False,
    )
    transform_matrix: Mapped[bytes | None] = mapped_column(LargeBinary)

    device = relationship("Device", back_populates="secret")


class DeviceWhitelistEntry(Base):
    __tablename__ = "device_whitelist"
    __table_args__ = (
        UniqueConstraint("device_id", "name", name="uq_whitelist_device_name"),
        Index("ix_whitelist_device", "device_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    device_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("devices.id", ondelete="CASCADE"), nullable=False
    )
    name: Mapped[str] = mapped_column(Text, nullable=False)
    cropped: Mapped[Any] = mapped_column(JSONB, nullable=True)

    device = relationship("Device", back_populates="whitelist")
    embeddings = relationship(
        "DeviceWhitelistEmbedding", back_populates="entry", cascade="all, delete-orphan"
    )

    # 1 to 1
    people_cluster = relationship(
        "PeopleCluster",
        back_populates="whitelist_entry",
        uselist=False,
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

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    entry_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("device_whitelist.id", ondelete="CASCADE"),
        nullable=False,
    )
    embedding: Mapped[Any] = mapped_column(Vector(512), nullable=False)
    entry = relationship("DeviceWhitelistEntry", back_populates="embeddings")


# ---------------------------------------------------------------------------
# Sensors
# ---------------------------------------------------------------------------

class SensorDevice(Base):
    __tablename__ = "sensor_devices"
    __table_args__ = (
        Index("ix_sensor_devices_device_id", "device_id"),
        Index("ix_sensor_devices_associated_user", "associated_user"),
        UniqueConstraint("device_id", "sensor_type", name="uq_sensor_device_id_type"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    device_id: Mapped[str] = mapped_column(Text, nullable=False)
    device_nickname: Mapped[str | None] = mapped_column(Text)
    secret: Mapped[str | None] = mapped_column(Text)
    sensor_type: Mapped[str] = mapped_column(Text, nullable=False)
    associated_user: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("devices.id", ondelete="SET NULL")
    )
    last_seen: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


# ---------------------------------------------------------------------------
# Image
# ---------------------------------------------------------------------------

class EmbeddingBase(Base):
    __abstract__ = True

    image_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("images.id", ondelete="CASCADE"), primary_key=True
    )


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
    embedding: Mapped[Any] = mapped_column(Vector(768), nullable=False)
    image = relationship("Image", back_populates="embedding", uselist=False)


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
    embedding: Mapped[Any] = mapped_column(Vector(768), nullable=False)
    image = relationship("Image", back_populates="clip_embedding", uselist=False)


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
        Index("ix_images_device_date_deleted", "device", "date", "deleted"),
        Index("ix_images_device_deleted_time", "device", "deleted", "deleted_time"),
        UniqueConstraint("device", "image_path", name="uq_device_image_path"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    mongo_id: Mapped[str | None] = mapped_column(Text, unique=True)
    image_path: Mapped[str] = mapped_column(Text, nullable=False)
    thumbnail: Mapped[str | None] = mapped_column(Text, nullable=True)
    is_video: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    timestamp: Mapped[datetime] = mapped_column(DateTime(timezone=False))
    local_timestamp: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    timezone: Mapped[str | None] = mapped_column(Text)
    date: Mapped[str | None] = mapped_column(Text)
    year: Mapped[int | None] = mapped_column(Integer)
    month: Mapped[int | None] = mapped_column(Integer)
    day: Mapped[int | None] = mapped_column(Integer)
    hour: Mapped[int | None] = mapped_column(Integer)
    seconds_from_midnight: Mapped[int | None] = mapped_column(Integer)
    device: Mapped[str | None] = mapped_column(Text)
    device_ref_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("devices.id"))
    segment_id: Mapped[int | None] = mapped_column(Integer)
    location_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("locations.id"))
    activity: Mapped[str | None] = mapped_column(Text)
    activity_group: Mapped[str | None] = mapped_column(Text)
    activity_confidence: Mapped[str | None] = mapped_column(Text)
    activity_description: Mapped[str | None] = mapped_column(Text)
    activity_tags: Mapped[str | None] = mapped_column(Text)
    deleted: Mapped[bool | None] = mapped_column(Boolean, default=False)
    deleted_time: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    new: Mapped[bool | None] = mapped_column(Boolean, default=False)
    proc_encoded: Mapped[bool | None] = mapped_column(Boolean, default=False)
    proc_yolo: Mapped[bool | None] = mapped_column(Boolean, default=False)
    proc_ocr: Mapped[bool | None] = mapped_column(Boolean, default=False)
    proc_deepface: Mapped[bool | None] = mapped_column(Boolean, default=False)
    proc_insightface: Mapped[bool | None] = mapped_column(Boolean, default=False)
    proc_face_recognition: Mapped[bool | None] = mapped_column(Boolean, default=False)
    proc_sam3: Mapped[bool | None] = mapped_column(Boolean, default=False)
    width: Mapped[int | None] = mapped_column(Integer)
    height: Mapped[int | None] = mapped_column(Integer)

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
        "ImageEmbedding", back_populates="image", uselist=False, cascade="all, delete-orphan"
    )
    clip_embedding = relationship(
        "CLIPEmbedding", back_populates="image", uselist=False, cascade="all, delete-orphan"
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
        UniqueConstraint("device_id", "timestamp", name="uq_raw_gps_device_time"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    device_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("devices.id", ondelete="CASCADE"),
        nullable=False,
    )
    latitude: Mapped[float] = mapped_column(Float, nullable=False)
    longitude: Mapped[float] = mapped_column(Float, nullable=False)
    elevation: Mapped[float | None] = mapped_column(Float)
    timestamp: Mapped[datetime] = mapped_column(DateTime(timezone=False))
    timezone: Mapped[str | None] = mapped_column(Text)
    # Fix-quality signal from android.location.Location (all optional — older
    # uploads / non-Android sources omit them):
    #   accuracy         = horizontal accuracy radius (m, 68% conf). Inverse-
    #                      variance weight 1/accuracy² for stop centroids; also
    #                      gates low-quality fixes before stay detection.
    #   vertical_accuracy= vertical accuracy radius (m, API 26+).
    #   speed            = ground speed (m/s) when hasSpeed().
    #   speed_accuracy   = speed accuracy (m/s, API 26+).
    #   bearing          = direction of travel (deg).
    #   provider         = fix source, e.g. "fused"/"gps"/"network".
    # No HDOP/fix_quality/satellite count — the fused API doesn't expose them.
    accuracy: Mapped[float | None] = mapped_column(Float)
    vertical_accuracy: Mapped[float | None] = mapped_column(Float)
    speed: Mapped[float | None] = mapped_column(Float)
    speed_accuracy: Mapped[float | None] = mapped_column(Float)
    bearing: Mapped[float | None] = mapped_column(Float)
    provider: Mapped[str | None] = mapped_column(Text)


class ImageGPS(Base):
    __tablename__ = "image_gps"
    __table_args__ = (
        Index("ix_gps_image", "image_id"),
        Index("ix_gps_geog", "geog", postgresql_using="gist"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    image_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("images.id", ondelete="CASCADE"),
        nullable=False,
        unique=True,
    )
    latitude: Mapped[float] = mapped_column(Float, nullable=False)
    longitude: Mapped[float] = mapped_column(Float, nullable=False)
    elevation: Mapped[float | None] = mapped_column(Float)
    timestamp: Mapped[float | None] = mapped_column(Float)
    formatted_time: Mapped[str | None] = mapped_column(Text)
    satellites: Mapped[int | None] = mapped_column(Integer)
    source: Mapped[str | None] = mapped_column(Text)
    gap_s: Mapped[float | None] = mapped_column(Float)
    mode: Mapped[str | None] = mapped_column(Text)  # transport mode of the segment this image falls in
    interpolated: Mapped[bool | None] = mapped_column(Boolean, default=False)
    timezone: Mapped[str | None] = mapped_column(Text)
    geog: Mapped[Any] = mapped_column(Geography(geometry_type="POINT", srid=4326), nullable=True)

    image = relationship("Image", back_populates="gps")


class PeopleCluster(Base):
    __tablename__ = "people_clusters"
    __table_args__ = (
        Index("ix_people_clusters_label", "cluster_label"),
        Index("ix_people_clusters_device", "device"),
        Index("ix_people_clusters_whitelist_entry", "whitelist_entry_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4, unique=True)
    cluster_label: Mapped[str] = mapped_column(Text, nullable=False)
    center_embedding: Mapped[Any] = mapped_column(Vector(512), nullable=False)
    device: Mapped[str | None] = mapped_column(Text)
    whitelist_entry_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("device_whitelist.id", ondelete="CASCADE"),
        nullable=True,
    )

    people = relationship("ImagePerson", back_populates="cluster")
    whitelist_entry = relationship("DeviceWhitelistEntry")


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

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    image_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("images.id", ondelete="CASCADE"), nullable=False
    )
    label: Mapped[str | None] = mapped_column(Text)
    confidence: Mapped[float | None] = mapped_column(Float)
    bbox: Mapped[Any] = mapped_column(JSONB, nullable=True)
    rel_bbox: Mapped[Any] = mapped_column(JSONB, nullable=True)
    embedding: Mapped[Any] = mapped_column(Vector(512), nullable=True)
    embedding_created_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=False))
    cluster_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("people_clusters.id", ondelete="SET NULL"),
    )

    image = relationship("Image", back_populates="people")
    cluster = relationship("PeopleCluster", back_populates="people")


class ImageObject(Base):
    __tablename__ = "image_objects"
    __table_args__ = (
        Index("ix_objects_image", "image_id"),
        Index("ix_objects_label", "label"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    image_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("images.id", ondelete="CASCADE"), nullable=False
    )
    label: Mapped[str | None] = mapped_column(Text)
    confidence: Mapped[float | None] = mapped_column(Float)
    bbox: Mapped[Any] = mapped_column(JSONB, nullable=True)
    rel_bbox: Mapped[Any] = mapped_column(JSONB, nullable=True)

    image = relationship("Image", back_populates="objects")


class ImageOCR(Base):
    __tablename__ = "image_ocr"
    __table_args__ = (
        Index("ix_ocr_image", "image_id"),
        Index(
            "ix_ocr_fts",
            func.to_tsvector(literal_column("'english'"), func.coalesce(Column("text"), "")),
            postgresql_using="gin",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    image_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("images.id", ondelete="CASCADE"), nullable=False
    )
    text: Mapped[str | None] = mapped_column(Text)
    confidence: Mapped[float | None] = mapped_column(Float)
    box_2d: Mapped[Any] = mapped_column(JSONB, nullable=True)
    polygon: Mapped[Any] = mapped_column(JSONB, nullable=True)

    image = relationship("Image", back_populates="ocr")


class AnnotationType(StrEnum):
    RECTANGLE = "rectangle"   # 2 points
    POLYGON = "polygon"       # n points, closed
    POLYLINE = "polyline"     # n points, open
    KEYPOINT = "keypoint"     # 1 point


class Annotation(Base):
    __tablename__ = "annotations"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    image_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("images.id", ondelete="CASCADE"),
        nullable=False,
    )
    anno_type: Mapped[AnnotationType] = mapped_column(
        Enum(AnnotationType), default=AnnotationType.POLYGON, nullable=False
    )
    points: Mapped[Any] = mapped_column(JSONB, nullable=True)
    label: Mapped[str | None] = mapped_column(Text)
    timestamp: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), server_default=func.now())
    author: Mapped[str | None] = mapped_column(Text)

    image = relationship("Image", back_populates="annotations")


# ---------------------------------------------------------------------------
# Health Data
# ---------------------------------------------------------------------------

class HeartRateData(Base):
    __tablename__ = "bio_heart_rate"
    __table_args__ = (
        Index("ix_hr_device_time", "device_id", "time_stamp"),
        UniqueConstraint("device_id", "time_stamp", name="uq_hr_device_time"),
    )
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    device_id: Mapped[str] = mapped_column(String(100))
    time_stamp: Mapped[int] = mapped_column(BigInteger, nullable=False)

    contact_status: Mapped[bool] = mapped_column(Boolean)
    contact_status_supported: Mapped[bool] = mapped_column(Boolean)
    corrected_hr: Mapped[int] = mapped_column(Integer)
    hr: Mapped[int] = mapped_column(Integer)
    ppg_quality: Mapped[int] = mapped_column(Integer)
    rr_available: Mapped[bool] = mapped_column(Boolean)
    rrs_ms: Mapped[list] = mapped_column(JSON, default=list)

    __mapper_args__ = {"polymorphic_identity": "HR"}


class MagnetometerData(Base):
    __tablename__ = "bio_magnetometer"
    __table_args__ = (
        Index("ix_mag_device_time", "device_id", "time_stamp"),
        UniqueConstraint("device_id", "time_stamp", name="uq_mag_device_time"),
    )
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    device_id: Mapped[str] = mapped_column(String(100))
    time_stamp: Mapped[int] = mapped_column(BigInteger, nullable=False)

    x: Mapped[float] = mapped_column(Float)
    y: Mapped[float] = mapped_column(Float)
    z: Mapped[float] = mapped_column(Float)

    __mapper_args__ = {"polymorphic_identity": "MAGNETOMETER"}


class AccelerometerData(Base):
    __tablename__ = "bio_accelerometer"
    __table_args__ = (
        Index("ix_acc_device_time", "device_id", "time_stamp"),
        UniqueConstraint("device_id", "time_stamp", name="uq_acc_device_time"),
    )
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    device_id: Mapped[str] = mapped_column(String(100))
    time_stamp: Mapped[int] = mapped_column(BigInteger, nullable=False)

    x: Mapped[float] = mapped_column(Float)
    y: Mapped[float] = mapped_column(Float)
    z: Mapped[float] = mapped_column(Float)

    __mapper_args__ = {"polymorphic_identity": "ACC"}


class GyroscopeData(Base):
    __tablename__ = "bio_gyroscope"
    __table_args__ = (
        Index("ix_gyro_device_time", "device_id", "time_stamp"),
        UniqueConstraint("device_id", "time_stamp", name="uq_gyro_device_time"),
    )
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    device_id: Mapped[str] = mapped_column(String(100))
    time_stamp: Mapped[int] = mapped_column(BigInteger, nullable=False)

    x: Mapped[float] = mapped_column(Float)
    y: Mapped[float] = mapped_column(Float)
    z: Mapped[float] = mapped_column(Float)

    __mapper_args__ = {"polymorphic_identity": "GYRO"}


class PPGData(Base):
    __tablename__ = "bio_ppg"
    __table_args__ = (
        Index("ix_ppg_device_time", "device_id", "time_stamp"),
        UniqueConstraint("device_id", "time_stamp", name="uq_ppg_device_time"),
    )
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    device_id: Mapped[str] = mapped_column(String(100))
    time_stamp: Mapped[int] = mapped_column(BigInteger, nullable=False)

    channel_samples: Mapped[list] = mapped_column(JSON, default=list)
    status_bits: Mapped[list] = mapped_column(JSON, default=list)

    __mapper_args__ = {"polymorphic_identity": "PPG"}


class PPIData(Base):
    __tablename__ = "bio_ppi"
    __table_args__ = (
        Index("ix_ppi_device_time", "device_id", "time_stamp"),
    )
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    device_id: Mapped[str] = mapped_column(String(100))
    time_stamp: Mapped[int] = mapped_column(BigInteger, nullable=False)

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
        UniqueConstraint("device_id", "time_stamp", name="uq_skin_temp_device_time"),
    )
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    device_id: Mapped[str] = mapped_column(String(100))
    time_stamp: Mapped[int] = mapped_column(BigInteger, nullable=False)

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

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    device: Mapped[str] = mapped_column(Text, nullable=False)
    date: Mapped[str] = mapped_column(Text, nullable=False)
    timestamp: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
    )
    read: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    type: Mapped[str] = mapped_column(Text, nullable=False)
    title: Mapped[str] = mapped_column(Text, nullable=False)
    body: Mapped[str | None] = mapped_column(Text)
    image_path: Mapped[str | None] = mapped_column(Text)
    segment_id: Mapped[int | None] = mapped_column(Integer)
    extra: Mapped[Any] = mapped_column(JSONB, nullable=True)


class PushSubscription(Base):
    """
    Browser Web Push subscriptions (one row per browser/device endpoint).
    Used to deliver notifications to phones even when the tab is closed.
    """
    __tablename__ = "push_subscription"
    __table_args__ = (
        Index("ix_push_sub_device", "device"),
        UniqueConstraint("endpoint", name="uq_push_sub_endpoint"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    device: Mapped[str] = mapped_column(Text, nullable=False)
    endpoint: Mapped[str] = mapped_column(Text, nullable=False)
    p256dh: Mapped[str] = mapped_column(Text, nullable=False)
    auth: Mapped[str] = mapped_column(Text, nullable=False)
    created: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
    )


class MealProfile(Base):
    """
    Per-device usual meal times, used to emit 'late_meal' notifications.

    `usual_minute` is minutes since local midnight (0-1439). Rows are either
    auto-learned from history (`auto=True`) or set manually by the user
    (`auto=False`); the learner never overwrites a manual row.
    """
    __tablename__ = "meal_profile"
    __table_args__ = (
        UniqueConstraint("device", "meal", name="uq_meal_profile_device_meal"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    device: Mapped[str] = mapped_column(Text, nullable=False)
    meal: Mapped[str] = mapped_column(Text, nullable=False)  # breakfast | lunch | dinner
    usual_minute: Mapped[int] = mapped_column(Integer, nullable=False)
    grace_minute: Mapped[int] = mapped_column(Integer, nullable=False, default=90)
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    auto: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    updated: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
    )


class SegmentFood(Base):
    """
    Structured food detail for one eating segment, produced by the food-pass
    vision task (services/food_pass.py). One row per (device, date, segment_id).

    Portions and calories are rough vision-based estimates (ballpark, not
    medical). ``items`` is a JSON list of {name, portion, calories}.
    """
    __tablename__ = "segment_food"
    __table_args__ = (
        UniqueConstraint("device", "date", "segment_id", name="uq_segment_food_seg"),
        Index("ix_segment_food_device_date", "device", "date"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    device: Mapped[str] = mapped_column(Text, nullable=False)
    date: Mapped[str] = mapped_column(Text, nullable=False)
    segment_id: Mapped[int] = mapped_column(Integer, nullable=False)
    items: Mapped[Any] = mapped_column(JSONB, nullable=False, default=list)  # [{name, portion, calories}]
    meal_type: Mapped[str | None] = mapped_column(Text)  # breakfast | lunch | dinner | snack
    total_calories: Mapped[int | None] = mapped_column(Integer)
    healthiness: Mapped[str | None] = mapped_column(Text)
    summary: Mapped[str | None] = mapped_column(Text)
    created: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )
    updated: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
    )


class BioDayStats(Base):
    """Per-day biometric aggregates, computed by the nightly Celery task."""
    __tablename__ = "bio_day_stats"
    __table_args__ = (
        Index("ix_bio_day_stats_device_date", "device_id", "date"),
        UniqueConstraint("device_id", "date", name="uq_bio_day_stats_device_date"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    device_id: Mapped[str] = mapped_column(String(100), nullable=False)
    date: Mapped[str] = mapped_column(String(10), nullable=False)
    avg_hr: Mapped[float | None] = mapped_column(Float)
    resting_hr: Mapped[float | None] = mapped_column(Float)
    max_hr: Mapped[float | None] = mapped_column(Float)
    rmssd: Mapped[float | None] = mapped_column(Float)
    step_count: Mapped[int | None] = mapped_column(Integer)
    sleep_start: Mapped[datetime | None] = mapped_column(DateTime)
    sleep_end: Mapped[datetime | None] = mapped_column(DateTime)
    sleep_minutes: Mapped[int | None] = mapped_column(Integer)
    computed_at: Mapped[datetime | None] = mapped_column(DateTime)


class VBSLog(Base):
    """VBS interaction log — one row per (inter-)action. Frontend-gated; rows
    are only written when the logging toggle is on. Used for post-hoc analysis
    (query→find time, per-task action funnel, modality mix, clock shift)."""
    __tablename__ = "vbs_log"
    __table_args__ = (
        Index("ix_vbs_log_evaluation", "evaluation_id"),
        Index("ix_vbs_log_event_ts", "event_ts"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    # received = server clock (ms); event_ts = client clock (ms). Both kept for
    # clock-shift/latency analysis.
    received: Mapped[int] = mapped_column(BigInteger, nullable=False)
    event_ts: Mapped[int] = mapped_column(BigInteger, nullable=False)
    client_ip: Mapped[str | None] = mapped_column(String(64))  # identifies the user/instance
    evaluation_id: Mapped[str | None] = mapped_column(String(100))
    task_name: Mapped[str | None] = mapped_column(String(255))
    category: Mapped[str] = mapped_column(String(50), nullable=False)
    type: Mapped[str | None] = mapped_column(String(50))
    value: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )


class DresSubmission(Base):
    """Server-side record of a DRES answer submission + its verdict. Lets
    query→find time be computed in SQL by joining the first CORRECT submission
    per task against the first vbs_log event for that task."""
    __tablename__ = "dres_submission"
    __table_args__ = (
        Index("ix_dres_submission_evaluation", "evaluation_id"),
        Index("ix_dres_submission_ts", "submitted_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    submitted_at: Mapped[int] = mapped_column(BigInteger, nullable=False)  # client clock, ms
    client_ip: Mapped[str | None] = mapped_column(String(64))
    evaluation_id: Mapped[str | None] = mapped_column(String(100))
    task_name: Mapped[str | None] = mapped_column(String(255))
    content_type: Mapped[str] = mapped_column(String(20), nullable=False)  # image | text
    content: Mapped[str | None] = mapped_column(Text)
    verdict: Mapped[str | None] = mapped_column(String(20))  # CORRECT | INCORRECT | ...
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )


class VBSResult(Base):
    """Ranked result list logged per query, so the target's rank over time can
    be reconstructed *after* DRES releases targets (days later). `results` is the
    displayed order (segments flattened), capped at 1000. Rank of a target =
    array position in `results`."""
    __tablename__ = "vbs_result"
    __table_args__ = (
        Index("ix_vbs_result_evaluation", "evaluation_id"),
        Index("ix_vbs_result_query_ts", "query_ts"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    query_ts: Mapped[int] = mapped_column(BigInteger, nullable=False)  # server clock, ms
    client_ip: Mapped[str | None] = mapped_column(String(64))
    evaluation_id: Mapped[str | None] = mapped_column(String(100))
    task_name: Mapped[str | None] = mapped_column(String(255))
    query_text: Mapped[str | None] = mapped_column(Text)
    sort_by: Mapped[str | None] = mapped_column(String(20))
    result_count: Mapped[int] = mapped_column(Integer, nullable=False)  # total before cap
    results: Mapped[Any] = mapped_column(JSONB, nullable=False)  # ordered image paths, <=1000
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )


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

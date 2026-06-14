"""add osm_pois offline POI gazetteer

Revision ID: d1e2f3a4b5c6
Revises: a1b2c3d4e5f6
Create Date: 2026-06-14

Offline OSM point-of-interest gazetteer for visual stop disambiguation.
Imported from a Geofabrik extract via batch/import_osm_pois.py; queried by
location/poi_gazetteer.nearby_pois via the geog GIST index.
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql
import geoalchemy2


revision = "d1e2f3a4b5c6"
down_revision = "a1b2c3d4e5f6"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "osm_pois",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("osm_type", sa.Text(), nullable=False),
        sa.Column("osm_id", sa.Text(), nullable=False),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("category", sa.Text(), nullable=True),
        sa.Column("wikidata_id", sa.Text(), nullable=True),
        sa.Column("latitude", sa.Float(), nullable=False),
        sa.Column("longitude", sa.Float(), nullable=False),
        sa.Column("country", sa.Text(), nullable=True),
        # spatial_index=False: the GIST index is created explicitly below so its
        # name is stable and geoalchemy2's DDL listener doesn't emit a duplicate.
        sa.Column(
            "geog",
            geoalchemy2.Geography(geometry_type="POINT", srid=4326, spatial_index=False),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("osm_type", "osm_id", name="uq_osm_pois_element"),
    )
    op.create_index("ix_osm_pois_geog", "osm_pois", ["geog"], postgresql_using="gist")

    # Coverage ledger for lazy on-demand POI fetching (Overpass per grid cell).
    op.create_table(
        "osm_tiles",
        sa.Column("tile_lat", sa.Float(), nullable=False),
        sa.Column("tile_lon", sa.Float(), nullable=False),
        sa.Column("fetched_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("status", sa.Text(), nullable=True),
        sa.PrimaryKeyConstraint("tile_lat", "tile_lon"),
    )


def downgrade() -> None:
    op.drop_table("osm_tiles")
    op.drop_index("ix_osm_pois_geog", table_name="osm_pois")
    op.drop_table("osm_pois")

"""Enrich Location schema with Nominatim / Wikidata fields

Revision ID: a1b2c3d4e5f6
Revises: 842455f262a2
Create Date: 2026-06-09

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'a1b2c3d4e5f6'
down_revision: Union[str, Sequence[str], None] = '842455f262a2'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('locations', sa.Column('suburb', sa.Text(), nullable=True))
    op.add_column('locations', sa.Column('city', sa.Text(), nullable=True))
    op.add_column('locations', sa.Column('region', sa.Text(), nullable=True))
    op.add_column('locations', sa.Column('postcode', sa.Text(), nullable=True))
    op.add_column('locations', sa.Column('osm_type', sa.Text(), nullable=True))
    op.add_column('locations', sa.Column('osm_id', sa.Text(), nullable=True))
    op.add_column('locations', sa.Column('wikidata_id', sa.Text(), nullable=True))
    op.add_column('locations', sa.Column('description', sa.Text(), nullable=True))
    op.add_column('locations', sa.Column('categories', sa.Text(), nullable=True))

    op.create_index('ix_locations_city', 'locations', ['city'])
    op.create_index('ix_locations_osm_id', 'locations', ['osm_id'])
    op.create_index('ix_locations_wikidata_id', 'locations', ['wikidata_id'])


def downgrade() -> None:
    op.drop_index('ix_locations_wikidata_id', table_name='locations')
    op.drop_index('ix_locations_osm_id', table_name='locations')
    op.drop_index('ix_locations_city', table_name='locations')

    op.drop_column('locations', 'categories')
    op.drop_column('locations', 'description')
    op.drop_column('locations', 'wikidata_id')
    op.drop_column('locations', 'osm_id')
    op.drop_column('locations', 'osm_type')
    op.drop_column('locations', 'postcode')
    op.drop_column('locations', 'region')
    op.drop_column('locations', 'city')
    op.drop_column('locations', 'suburb')

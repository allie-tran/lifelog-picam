"""Add face recognition mode flag and device-scope clusters

Revision ID: f9e8d7c6b5a4
Revises: c8e1f2a3b4d5
Create Date: 2026-06-10 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'f9e8d7c6b5a4'
down_revision: Union[str, Sequence[str], None] = 'c8e1f2a3b4d5'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('devices', sa.Column('keep_face_recognition', sa.Boolean(), nullable=False, server_default='false'))
    op.add_column('people_clusters', sa.Column('device', sa.Text(), nullable=True))
    op.add_column('people_clusters', sa.Column('whitelist_entry_id', sa.UUID(), nullable=True))
    op.create_foreign_key(
        'fk_people_clusters_whitelist_entry',
        'people_clusters', 'device_whitelist',
        ['whitelist_entry_id'], ['id'],
        ondelete='CASCADE',
    )
    op.create_index('ix_people_clusters_device', 'people_clusters', ['device'], unique=False)
    op.create_index('ix_people_clusters_whitelist_entry', 'people_clusters', ['whitelist_entry_id'], unique=False)


def downgrade() -> None:
    op.drop_index('ix_people_clusters_whitelist_entry', table_name='people_clusters')
    op.drop_index('ix_people_clusters_device', table_name='people_clusters')
    op.drop_constraint('fk_people_clusters_whitelist_entry', 'people_clusters', type_='foreignkey')
    op.drop_column('people_clusters', 'whitelist_entry_id')
    op.drop_column('people_clusters', 'device')
    op.drop_column('devices', 'keep_face_recognition')

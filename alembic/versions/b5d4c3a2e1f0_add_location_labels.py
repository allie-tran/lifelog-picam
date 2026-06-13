"""Add per-user location_labels table

Revision ID: b5d4c3a2e1f0
Revises: a3b2c1d4e5f6
Create Date: 2026-06-13 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID


revision: str = 'b5d4c3a2e1f0'
down_revision: Union[str, Sequence[str], None] = 'a3b2c1d4e5f6'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'location_labels',
        sa.Column('id', UUID(as_uuid=True), nullable=False),
        sa.Column('username', sa.Text(), nullable=False),
        sa.Column('location_id', UUID(as_uuid=True), nullable=False),
        sa.Column('label', sa.Text(), nullable=False),
        sa.Column('label_kind', sa.Text(), nullable=False, server_default='other'),
        sa.ForeignKeyConstraint(['location_id'], ['locations.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('username', 'location_id', name='uq_location_label_user_loc'),
    )
    op.create_index('ix_location_labels_username', 'location_labels', ['username'])
    op.create_index('ix_location_labels_location', 'location_labels', ['location_id'])


def downgrade() -> None:
    op.drop_index('ix_location_labels_location', table_name='location_labels')
    op.drop_index('ix_location_labels_username', table_name='location_labels')
    op.drop_table('location_labels')

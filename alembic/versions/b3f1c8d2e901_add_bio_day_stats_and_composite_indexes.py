"""add bio_day_stats and composite indexes

Revision ID: b3f1c8d2e901
Revises: 9d7e698bd15e
Create Date: 2026-06-08 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'b3f1c8d2e901'
down_revision: Union[str, Sequence[str], None] = '9d7e698bd15e'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # ── bio_day_stats ────────────────────────────────────────────────────────
    op.create_table(
        'bio_day_stats',
        sa.Column('id', sa.UUID(), nullable=False),
        sa.Column('device_id', sa.String(100), nullable=False),
        sa.Column('date', sa.String(10), nullable=False),
        sa.Column('avg_hr', sa.Float(), nullable=True),
        sa.Column('resting_hr', sa.Float(), nullable=True),
        sa.Column('max_hr', sa.Float(), nullable=True),
        sa.Column('rmssd', sa.Float(), nullable=True),
        sa.Column('step_count', sa.Integer(), nullable=True),
        sa.Column('sleep_start', sa.DateTime(), nullable=True),
        sa.Column('sleep_end', sa.DateTime(), nullable=True),
        sa.Column('sleep_minutes', sa.Integer(), nullable=True),
        sa.Column('computed_at', sa.DateTime(), nullable=True),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('device_id', 'date', name='uq_bio_day_stats_device_date'),
    )
    op.create_index('ix_bio_day_stats_device_date', 'bio_day_stats', ['device_id', 'date'])

    # ── Composite indexes on images for common query patterns ────────────────
    op.create_index(
        'ix_images_device_date_deleted', 'images', ['device', 'date', 'deleted']
    )
    op.create_index(
        'ix_images_device_deleted_time', 'images', ['device', 'deleted', 'deleted_time']
    )


def downgrade() -> None:
    op.drop_index('ix_images_device_deleted_time', table_name='images')
    op.drop_index('ix_images_device_date_deleted', table_name='images')
    op.drop_index('ix_bio_day_stats_device_date', table_name='bio_day_stats')
    op.drop_table('bio_day_stats')

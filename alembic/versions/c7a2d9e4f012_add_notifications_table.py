"""add notifications table

Revision ID: c7a2d9e4f012
Revises: b3f1c8d2e901
Create Date: 2026-06-08 00:01:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID, JSONB


revision: str = 'c7a2d9e4f012'
down_revision: Union[str, Sequence[str], None] = 'b3f1c8d2e901'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'notifications',
        sa.Column('id', UUID(as_uuid=True), nullable=False),
        sa.Column('device', sa.Text(), nullable=False),
        sa.Column('date', sa.Text(), nullable=False),
        sa.Column('timestamp', sa.DateTime(timezone=True), nullable=True),
        sa.Column('read', sa.Boolean(), nullable=False, server_default=sa.text('false')),
        sa.Column('type', sa.Text(), nullable=False),
        sa.Column('title', sa.Text(), nullable=False),
        sa.Column('body', sa.Text(), nullable=True),
        sa.Column('image_path', sa.Text(), nullable=True),
        sa.Column('segment_id', sa.Integer(), nullable=True),
        sa.Column('extra', JSONB(), nullable=True),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('ix_notif_device_date', 'notifications', ['device', 'date'])
    op.create_index('ix_notif_device_read', 'notifications', ['device', 'read'])
    # Partial unique indexes to handle NULL segment_id correctly.
    # A regular unique constraint would treat all NULLs as distinct; partial indexes
    # give us idempotent ON CONFLICT DO NOTHING for both segment-level and day-level events.
    op.execute(
        "CREATE UNIQUE INDEX uq_notif_with_segment "
        "ON notifications (device, date, segment_id, type) "
        "WHERE segment_id IS NOT NULL"
    )
    op.execute(
        "CREATE UNIQUE INDEX uq_notif_no_segment "
        "ON notifications (device, date, type) "
        "WHERE segment_id IS NULL"
    )


def downgrade() -> None:
    op.execute('DROP INDEX IF EXISTS uq_notif_no_segment')
    op.execute('DROP INDEX IF EXISTS uq_notif_with_segment')
    op.drop_index('ix_notif_device_read', table_name='notifications')
    op.drop_index('ix_notif_device_date', table_name='notifications')
    op.drop_table('notifications')

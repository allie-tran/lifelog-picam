"""Add last_seen to sensor_devices

Revision ID: b7f0d1e2c3a4
Revises: a1b2c3d4e5f6
Create Date: 2026-06-09

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'b7f0d1e2c3a4'
down_revision: Union[str, Sequence[str], None] = '5b098c80449e'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('sensor_devices', sa.Column('last_seen', sa.DateTime(timezone=True), nullable=True))
    op.create_index('ix_sensor_devices_last_seen', 'sensor_devices', ['last_seen'])


def downgrade() -> None:
    op.drop_index('ix_sensor_devices_last_seen', table_name='sensor_devices')
    op.drop_column('sensor_devices', 'last_seen')

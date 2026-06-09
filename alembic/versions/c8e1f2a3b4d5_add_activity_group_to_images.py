"""Add activity_group to images

Revision ID: c8e1f2a3b4d5
Revises: b7f0d1e2c3a4
Create Date: 2026-06-09

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'c8e1f2a3b4d5'
down_revision: Union[str, Sequence[str], None] = 'b7f0d1e2c3a4'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('images', sa.Column('activity_group', sa.Text(), nullable=True))
    op.create_index('ix_images_activity_group', 'images', ['activity_group'])


def downgrade() -> None:
    op.drop_index('ix_images_activity_group', table_name='images')
    op.drop_column('images', 'activity_group')

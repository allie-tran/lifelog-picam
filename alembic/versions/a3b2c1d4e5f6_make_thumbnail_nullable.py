"""Make image thumbnail nullable

Revision ID: a3b2c1d4e5f6
Revises: f10f0aef6b1b
Create Date: 2026-06-12 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
import pgvector.sqlalchemy


revision: str = 'a3b2c1d4e5f6'
down_revision: Union[str, Sequence[str], None] = 'f10f0aef6b1b'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.alter_column('images', 'thumbnail', existing_type=sa.Text(), nullable=True)


def downgrade() -> None:
    op.execute(
        "UPDATE images SET thumbnail = regexp_replace(image_path, '\\.jpg$', '.webp') "
        "WHERE thumbnail IS NULL"
    )
    op.alter_column('images', 'thumbnail', existing_type=sa.Text(), nullable=False)

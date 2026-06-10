"""add activity_tags to images

Revision ID: 6853f9094dfb
Revises: f9e8d7c6b5a4
Create Date: 2026-06-10 17:08:03.196964

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
import pgvector.sqlalchemy

# revision identifiers, used by Alembic.
revision: str = '6853f9094dfb'
down_revision: Union[str, Sequence[str], None] = 'f9e8d7c6b5a4'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('images', sa.Column('activity_tags', sa.Text(), nullable=True))


def downgrade() -> None:
    op.drop_column('images', 'activity_tags')

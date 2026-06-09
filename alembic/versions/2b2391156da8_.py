"""empty message

Revision ID: 2b2391156da8
Revises: a1b2c3d4e5f6, aed60be9ead9
Create Date: 2026-06-09 15:16:21.286169

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
import pgvector.sqlalchemy  # <--- Add this line here


# revision identifiers, used by Alembic.
revision: str = '2b2391156da8'
down_revision: Union[str, Sequence[str], None] = ('a1b2c3d4e5f6', 'aed60be9ead9')
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    pass


def downgrade() -> None:
    """Downgrade schema."""
    pass

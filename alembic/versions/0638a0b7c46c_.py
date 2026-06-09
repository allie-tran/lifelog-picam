"""empty message

Revision ID: 0638a0b7c46c
Revises: 8e034ac1494b, c7a2d9e4f012
Create Date: 2026-06-09 09:38:50.040871

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
import pgvector.sqlalchemy  # <--- Add this line here


# revision identifiers, used by Alembic.
revision: str = '0638a0b7c46c'
down_revision: Union[str, Sequence[str], None] = ('8e034ac1494b', 'c7a2d9e4f012')
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    pass


def downgrade() -> None:
    """Downgrade schema."""
    pass

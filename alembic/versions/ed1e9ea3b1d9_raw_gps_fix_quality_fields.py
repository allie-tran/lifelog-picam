"""raw_gps fix-quality fields (accuracy, vertical_accuracy, speed, speed_accuracy, bearing, provider)

Revision ID: ed1e9ea3b1d9
Revises: 6cf0be148008
Create Date: 2026-07-20

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'ed1e9ea3b1d9'
down_revision: Union[str, Sequence[str], None] = '6cf0be148008'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    # All nullable — older / non-Android uploads omit these fields.
    op.add_column('raw_gps', sa.Column('accuracy', sa.Float(), nullable=True))
    op.add_column('raw_gps', sa.Column('vertical_accuracy', sa.Float(), nullable=True))
    op.add_column('raw_gps', sa.Column('speed', sa.Float(), nullable=True))
    op.add_column('raw_gps', sa.Column('speed_accuracy', sa.Float(), nullable=True))
    op.add_column('raw_gps', sa.Column('bearing', sa.Float(), nullable=True))
    op.add_column('raw_gps', sa.Column('provider', sa.Text(), nullable=True))


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column('raw_gps', 'provider')
    op.drop_column('raw_gps', 'bearing')
    op.drop_column('raw_gps', 'speed_accuracy')
    op.drop_column('raw_gps', 'speed')
    op.drop_column('raw_gps', 'vertical_accuracy')
    op.drop_column('raw_gps', 'accuracy')

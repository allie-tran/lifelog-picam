"""add segment_food.segment_ids

Records the segment set each meal covers so a rebuild can detect when a meal's
membership changed (re-segmentation) and refresh the food pass.

Revision ID: a3c5e7f9b2d1
Revises: f7a1c3b9e2d5
Create Date: 2026-07-26
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
import pgvector.sqlalchemy  # noqa: F401
from sqlalchemy.dialects import postgresql

revision: str = "a3c5e7f9b2d1"
down_revision: Union[str, Sequence[str], None] = "f7a1c3b9e2d5"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "segment_food",
        sa.Column(
            "segment_ids",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'[]'::jsonb"),
        ),
    )


def downgrade() -> None:
    op.drop_column("segment_food", "segment_ids")

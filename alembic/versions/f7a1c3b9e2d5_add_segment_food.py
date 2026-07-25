"""add segment_food table

Structured per-eating-segment food detail (items, portion, rough calories,
meal type, healthiness) produced by the food-pass vision task.

Revision ID: f7a1c3b9e2d5
Revises: e2f4a6c8d0b1
Create Date: 2026-07-25
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
import pgvector.sqlalchemy  # noqa: F401 — models.py uses Vector; keep import for autogen parity
from sqlalchemy.dialects import postgresql

revision: str = "f7a1c3b9e2d5"
down_revision: Union[str, Sequence[str], None] = "e2f4a6c8d0b1"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "segment_food",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("device", sa.Text(), nullable=False),
        sa.Column("date", sa.Text(), nullable=False),
        sa.Column("segment_id", sa.Integer(), nullable=False),
        sa.Column("items", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("meal_type", sa.Text(), nullable=True),
        sa.Column("total_calories", sa.Integer(), nullable=True),
        sa.Column("healthiness", sa.Text(), nullable=True),
        sa.Column("summary", sa.Text(), nullable=True),
        sa.Column("created", sa.DateTime(timezone=True), nullable=True),
        sa.Column("updated", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("device", "date", "segment_id", name="uq_segment_food_seg"),
    )
    op.create_index(
        "ix_segment_food_device_date", "segment_food", ["device", "date"], unique=False
    )


def downgrade() -> None:
    op.drop_index("ix_segment_food_device_date", table_name="segment_food")
    op.drop_table("segment_food")

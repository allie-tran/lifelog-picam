"""add locations.user_confirmed

Marks a Location whose venue the user corrected via chat (stop_correction) so
the GPS pipeline won't re-resolve/overwrite it on a later resync.

Revision ID: e2f4a6c8d0b1
Revises: ed1e9ea3b1d9
Create Date: 2026-07-23
"""
from alembic import op
import sqlalchemy as sa


revision = "e2f4a6c8d0b1"
down_revision = "ed1e9ea3b1d9"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "locations",
        sa.Column(
            "user_confirmed",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
        ),
    )


def downgrade() -> None:
    op.drop_column("locations", "user_confirmed")

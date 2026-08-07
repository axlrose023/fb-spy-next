"""Add normalized Facebook ad language.

Revision ID: d7b1f4a9c632
Revises: c8e7319a42fd
Create Date: 2026-07-17 08:15:00
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "d7b1f4a9c632"
down_revision: str | None = "c8e7319a42fd"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "facebook_ads",
        sa.Column("language", sa.String(length=16), nullable=True),
    )
    op.create_index(
        "facebook_ads_language_idx",
        "facebook_ads",
        ["language"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("facebook_ads_language_idx", table_name="facebook_ads")
    op.drop_column("facebook_ads", "language")

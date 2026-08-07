"""landing_archives

Revision ID: 5d8b5a3f0a12
Revises: 9f1c4a7b2e80
Create Date: 2026-06-26 17:30:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "5d8b5a3f0a12"
down_revision: str | None = "9f1c4a7b2e80"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "facebook_ads",
        sa.Column("landing_archive_path", sa.Text(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("facebook_ads", "landing_archive_path")

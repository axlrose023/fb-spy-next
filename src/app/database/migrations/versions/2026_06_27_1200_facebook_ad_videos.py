"""facebook_ad_videos

Revision ID: 7f35c2a9b6d1
Revises: 5d8b5a3f0a12
Create Date: 2026-06-27 12:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "7f35c2a9b6d1"
down_revision: str | None = "5d8b5a3f0a12"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "facebook_ads",
        sa.Column("video_path", sa.Text(), nullable=False, server_default=""),
    )
    op.alter_column("facebook_ads", "video_path", server_default=None)


def downgrade() -> None:
    op.drop_column("facebook_ads", "video_path")

"""facebook_run_profile_geo

Revision ID: b6a2d41f9087
Revises: 7f35c2a9b6d1
Create Date: 2026-07-06 12:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "b6a2d41f9087"
down_revision: str | None = "7f35c2a9b6d1"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "facebook_runs",
        sa.Column("octo_profile_uuid", sa.String(length=64), nullable=True),
    )
    op.add_column(
        "facebook_runs",
        sa.Column("profile_country", sa.String(length=64), nullable=True),
    )
    op.add_column(
        "facebook_runs",
        sa.Column("octo_ip", sa.String(length=64), nullable=True),
    )
    op.create_index(
        op.f("facebook_runs_octo_profile_uuid_idx"),
        "facebook_runs",
        ["octo_profile_uuid"],
    )
    op.create_index(
        op.f("facebook_runs_profile_country_idx"),
        "facebook_runs",
        ["profile_country"],
    )


def downgrade() -> None:
    op.drop_index(op.f("facebook_runs_profile_country_idx"), table_name="facebook_runs")
    op.drop_index(
        op.f("facebook_runs_octo_profile_uuid_idx"),
        table_name="facebook_runs",
    )
    op.drop_column("facebook_runs", "octo_ip")
    op.drop_column("facebook_runs", "profile_country")
    op.drop_column("facebook_runs", "octo_profile_uuid")

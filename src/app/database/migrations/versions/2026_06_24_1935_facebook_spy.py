"""facebook_spy

Revision ID: 2b0ed0ccf524
Revises: aac9c3981adb
Create Date: 2026-06-24 19:35:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "2b0ed0ccf524"
down_revision: str | None = "aac9c3981adb"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "facebook_runs",
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("title", sa.String(length=255), nullable=True),
        sa.Column("requested_minutes", sa.Float(), nullable=False),
        sa.Column("collect_scrolls", sa.Integer(), nullable=False),
        sa.Column("resolve_max", sa.Integer(), nullable=False),
        sa.Column("scroll_px", sa.Integer(), nullable=False),
        sa.Column("debug", sa.Boolean(), nullable=False),
        sa.Column("no_resolve", sa.Boolean(), nullable=False),
        sa.Column("no_shots", sa.Boolean(), nullable=False),
        sa.Column("out_root", sa.Text(), nullable=True),
        sa.Column("runner_run_dir", sa.Text(), nullable=True),
        sa.Column("ads_json_path", sa.Text(), nullable=True),
        sa.Column("log_path", sa.Text(), nullable=True),
        sa.Column("debug_dir", sa.Text(), nullable=True),
        sa.Column("process_pid", sa.Integer(), nullable=True),
        sa.Column("return_code", sa.Integer(), nullable=True),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("total_ads", sa.Integer(), nullable=False),
        sa.Column("link_ads", sa.Integer(), nullable=False),
        sa.Column("resolved_ads", sa.Integer(), nullable=False),
        sa.Column("video_ads", sa.Integer(), nullable=False),
        sa.Column("bad_screenshots", sa.Integer(), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("id", sa.UUID(), server_default=sa.text("uuidv7()"), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("facebook_runs_pkey")),
    )
    op.create_index(op.f("facebook_runs_status_idx"), "facebook_runs", ["status"])

    op.create_table(
        "facebook_ads",
        sa.Column("run_id", sa.UUID(), nullable=False),
        sa.Column("source_index", sa.Integer(), nullable=True),
        sa.Column("source_key", sa.Text(), nullable=True),
        sa.Column("advertiser", sa.String(length=512), nullable=False),
        sa.Column("ad_type", sa.String(length=32), nullable=False),
        sa.Column("format", sa.String(length=32), nullable=False),
        sa.Column("vertical", sa.String(length=64), nullable=True),
        sa.Column("country", sa.String(length=64), nullable=True),
        sa.Column("platform", sa.String(length=64), nullable=False),
        sa.Column("placement", sa.String(length=64), nullable=False),
        sa.Column("cloaking", sa.Boolean(), nullable=True),
        sa.Column("has_video", sa.Boolean(), nullable=False),
        sa.Column("displayed_domain", sa.String(length=512), nullable=False),
        sa.Column("headline", sa.Text(), nullable=False),
        sa.Column("ad_text", sa.Text(), nullable=False),
        sa.Column("cta", sa.String(length=255), nullable=False),
        sa.Column("creative_img", sa.Text(), nullable=False),
        sa.Column("screenshot_path", sa.Text(), nullable=False),
        sa.Column("screenshot_ok", sa.Boolean(), nullable=True),
        sa.Column("screenshot_issue", sa.String(length=255), nullable=True),
        sa.Column("landing_full", sa.Text(), nullable=True),
        sa.Column("landing_clean", sa.Text(), nullable=True),
        sa.Column("landing_screenshot_path", sa.Text(), nullable=True),
        sa.Column("fb_ad_id", sa.String(length=128), nullable=True),
        sa.Column("utm", sa.JSON(), nullable=False),
        sa.Column("captured_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("id", sa.UUID(), server_default=sa.text("uuidv7()"), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["run_id"],
            ["facebook_runs.id"],
            name=op.f("facebook_ads_run_id_fkey"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("facebook_ads_pkey")),
    )
    for column in (
        "run_id",
        "advertiser",
        "displayed_domain",
        "fb_ad_id",
        "ad_type",
        "format",
        "vertical",
        "country",
        "platform",
        "placement",
        "cloaking",
    ):
        op.create_index(op.f(f"facebook_ads_{column}_idx"), "facebook_ads", [column])


def downgrade() -> None:
    for column in (
        "cloaking",
        "placement",
        "platform",
        "country",
        "vertical",
        "format",
        "ad_type",
        "fb_ad_id",
        "displayed_domain",
        "advertiser",
        "run_id",
    ):
        op.drop_index(op.f(f"facebook_ads_{column}_idx"), table_name="facebook_ads")
    op.drop_table("facebook_ads")
    op.drop_index(op.f("facebook_runs_status_idx"), table_name="facebook_runs")
    op.drop_table("facebook_runs")

"""Deduplicate Facebook ads by geo and Facebook ad ID.

Revision ID: c8e7319a42fd
Revises: b6a2d41f9087
Create Date: 2026-07-17 07:00:00
"""

from collections.abc import Sequence

from alembic import op

revision: str = "c8e7319a42fd"
down_revision: str | None = "b6a2d41f9087"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

INDEX_NAME = "facebook_ads_geo_fb_ad_id_uidx"


def upgrade() -> None:
    op.execute(
        """
        UPDATE facebook_ads
        SET country = btrim(country),
            fb_ad_id = btrim(fb_ad_id)
        WHERE country IS NOT NULL
          AND fb_ad_id IS NOT NULL
          AND (country <> btrim(country) OR fb_ad_id <> btrim(fb_ad_id))
        """
    )
    op.execute(
        """
        WITH ranked AS (
            SELECT id,
                   row_number() OVER (
                       PARTITION BY lower(country), fb_ad_id
                       ORDER BY captured_at DESC NULLS LAST,
                                created_at DESC,
                                id DESC
                   ) AS duplicate_rank
            FROM facebook_ads
            WHERE country IS NOT NULL
              AND country <> ''
              AND fb_ad_id IS NOT NULL
              AND fb_ad_id <> ''
        )
        DELETE FROM facebook_ads AS ads
        USING ranked
        WHERE ads.id = ranked.id
          AND ranked.duplicate_rank > 1
        """
    )
    op.execute(
        f"""
        CREATE UNIQUE INDEX {INDEX_NAME}
        ON facebook_ads (lower(country), fb_ad_id)
        WHERE country IS NOT NULL
          AND country <> ''
          AND fb_ad_id IS NOT NULL
          AND fb_ad_id <> ''
        """
    )


def downgrade() -> None:
    op.execute(f"DROP INDEX IF EXISTS {INDEX_NAME}")

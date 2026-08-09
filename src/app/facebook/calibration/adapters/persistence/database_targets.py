from __future__ import annotations

from typing import Any
from uuid import UUID

from sqlalchemy import select

from app.ad_library import FacebookAdRecord
from app.database.engine import SessionFactory
from app.facebook.runs import FacebookRunRecord
from app.settings import Config

from ...planning import CalibrationTarget, select_calibration_targets


async def load_targets_from_db(
    config: Config,
    *,
    country: str | None = None,
    octo_profile_uuid: str | None = None,
    run_id: UUID | None = None,
    limit: int = 20,
    max_per_domain: int = 2,
    include_creative_fallback: bool = False,
) -> list[CalibrationTarget]:
    fetch_limit = max(limit * 8, limit, 50)
    async with SessionFactory() as session:
        statement = (
            select(FacebookAdRecord, FacebookRunRecord)
            .join(
                FacebookRunRecord,
                FacebookAdRecord.run_id == FacebookRunRecord.id,
            )
            .order_by(
                FacebookAdRecord.captured_at.desc().nullslast(),
                FacebookAdRecord.created_at.desc(),
            )
            .limit(fetch_limit)
        )
        if country:
            statement = statement.where(FacebookAdRecord.country == country)
        if octo_profile_uuid:
            statement = statement.where(
                FacebookRunRecord.octo_profile_uuid == octo_profile_uuid
            )
        if run_id:
            statement = statement.where(FacebookAdRecord.run_id == run_id)
        if not include_creative_fallback:
            statement = statement.where(FacebookAdRecord.landing_full.is_not(None))

        rows = (await session.execute(statement)).all()

    raw_ads = [_raw_from_db_row(ad, run, config) for ad, run in rows]
    targets: list[CalibrationTarget] = select_calibration_targets(
        raw_ads,
        country=None,
        limit=limit,
        max_per_domain=max_per_domain,
        include_creative_fallback=include_creative_fallback,
    )
    return targets


def _raw_from_db_row(ad: Any, run: Any, config: Config) -> dict[str, Any]:
    return {
        "run_id": str(ad.run_id),
        "source_index": ad.source_index,
        "advertiser": ad.advertiser,
        "displayed_domain": ad.displayed_domain,
        "headline": ad.headline,
        "ad_text": ad.ad_text,
        "cta": ad.cta,
        "cta_href": None,
        "country": ad.country or run.profile_country or config.facebook.default_country,
        "fb_ad_id": ad.fb_ad_id,
        "feed_element_id": None,
        "facebook_page_url": None,
        "facebook_post_url": None,
        "landing_full": ad.landing_full,
        "landing_clean": ad.landing_clean,
        "creative_img": ad.creative_img,
        "captured_at": ad.captured_at.isoformat() if ad.captured_at else None,
        "_source": "db",
    }

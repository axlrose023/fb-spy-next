from collections.abc import Sequence
from uuid import UUID

from sqlalchemy import BinaryExpression, delete, func, or_, select, tuple_
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.modules.ads.models import FacebookAd


class FacebookAdGateway:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def get_total_count(self, filters: list[BinaryExpression]) -> int:
        stmt = select(func.count()).select_from(FacebookAd).where(*filters)
        result = await self.session.execute(stmt)
        return result.scalar() or 0

    async def get_all(
        self,
        limit: int,
        offset: int,
        filters: list[BinaryExpression],
        order_by: str = "-captured_at",
    ) -> Sequence[FacebookAd]:
        sort_field = order_by.removeprefix("-")
        column = getattr(FacebookAd, sort_field, FacebookAd.captured_at)
        if order_by.startswith("-"):
            column = column.desc()
        stmt = (
            select(FacebookAd)
            .where(*filters)
            .order_by(column)
            .offset(offset=offset)
            .limit(limit)
        )
        result = await self.session.execute(stmt)
        return result.scalars().all()

    async def get_by_id(self, ad_id: UUID) -> FacebookAd | None:
        stmt = select(FacebookAd).where(FacebookAd.id == ad_id)
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()

    async def existing_fb_ad_keys(
        self,
        keys: set[tuple[str, str]],
    ) -> set[tuple[str, str]]:
        if not keys:
            return set()
        identity = tuple_(
            func.lower(func.trim(FacebookAd.country)),
            func.trim(FacebookAd.fb_ad_id),
        )
        stmt = select(FacebookAd.country, FacebookAd.fb_ad_id).where(
            identity.in_(sorted(keys))
        )
        rows = (await self.session.execute(stmt)).all()
        return {
            (country.strip().lower(), fb_ad_id.strip())
            for country, fb_ad_id in rows
            if country and fb_ad_id
        }

    async def create_many(self, ads: list[FacebookAd]) -> list[FacebookAd]:
        self.session.add_all(ads)
        await self.session.flush()
        return ads

    async def delete_by_run_id(self, run_id: UUID) -> None:
        await self.session.execute(delete(FacebookAd).where(FacebookAd.run_id == run_id))
        await self.session.flush()


def build_ad_search_filter(query: str) -> BinaryExpression:
    pattern = f"%{query}%"
    return or_(
        FacebookAd.advertiser.ilike(pattern),
        FacebookAd.displayed_domain.ilike(pattern),
        FacebookAd.headline.ilike(pattern),
        FacebookAd.ad_text.ilike(pattern),
        FacebookAd.cta.ilike(pattern),
        FacebookAd.landing_clean.ilike(pattern),
    )

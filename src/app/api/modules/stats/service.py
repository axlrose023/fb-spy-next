from sqlalchemy import func, select

from app.api.modules.ads.models import FacebookAd
from app.api.modules.stats.schema import AdsStatsResponse, FacetItem
from app.database.uow import UnitOfWork


class StatsService:
    def __init__(self, uow: UnitOfWork):
        self.uow = uow

    async def get_ads_stats(self) -> AdsStatsResponse:
        total = await self._count()
        return AdsStatsResponse(
            total_ads=total,
            link_ads=await self._count(FacebookAd.ad_type == "link"),
            resolved_ads=await self._count(FacebookAd.landing_full.is_not(None)),
            video_ads=await self._count(
                (FacebookAd.has_video.is_(True)) | (FacebookAd.ad_type == "video")
            ),
            bad_screenshots=await self._count(FacebookAd.screenshot_ok.is_(False)),
            by_type=await self._facet(FacebookAd.ad_type),
            by_format=await self._facet(FacebookAd.format),
            by_vertical=await self._facet(FacebookAd.vertical),
            by_country=await self._facet(FacebookAd.country),
            by_language=await self._facet(FacebookAd.language),
            by_platform=await self._facet(FacebookAd.platform),
            by_placement=await self._facet(FacebookAd.placement),
            by_domain=await self._facet(FacebookAd.displayed_domain),
            by_advertiser=await self._facet(FacebookAd.advertiser),
            by_cta=await self._facet(FacebookAd.cta),
        )

    async def _count(self, *where) -> int:
        stmt = select(func.count()).select_from(FacebookAd).where(*where)
        result = await self.uow.session.execute(stmt)
        return result.scalar() or 0

    async def _facet(self, column, limit: int = 30) -> list[FacetItem]:
        stmt = (
            select(column, func.count())
            .select_from(FacebookAd)
            .where(column.is_not(None), column != "")
            .group_by(column)
            .order_by(func.count().desc())
            .limit(limit)
        )
        result = await self.uow.session.execute(stmt)
        return [FacetItem(value=value, count=count) for value, count in result.all()]

from __future__ import annotations

from typing import Any

from sqlalchemy import Select, case, func, literal, select, union_all
from sqlalchemy.ext.asyncio import AsyncSession

from ..models import AdStatistics, Facet


class SqlAlchemyAdStatisticsReader:
    def __init__(self, session: AsyncSession, ad_record: type[Any]) -> None:
        self._session = session
        self._ads = ad_record

    async def read_ads_statistics(self, *, facet_limit: int) -> AdStatistics:
        ads = self._ads
        summary = (
            await self._session.execute(
                select(
                    func.count().label("total_ads"),
                    self._conditional_count(ads.ad_type == "link").label(
                        "link_ads"
                    ),
                    self._conditional_count(ads.landing_full.is_not(None)).label(
                        "resolved_ads"
                    ),
                    self._conditional_count(
                        ads.has_video.is_(True) | (ads.ad_type == "video")
                    ).label("video_ads"),
                    self._conditional_count(ads.screenshot_ok.is_(False)).label(
                        "bad_screenshots"
                    ),
                ).select_from(ads)
            )
        ).one()._mapping
        facets = await self._read_facets(facet_limit)
        return AdStatistics(
            total_ads=int(summary["total_ads"] or 0),
            link_ads=int(summary["link_ads"] or 0),
            resolved_ads=int(summary["resolved_ads"] or 0),
            video_ads=int(summary["video_ads"] or 0),
            bad_screenshots=int(summary["bad_screenshots"] or 0),
            by_type=facets["by_type"],
            by_format=facets["by_format"],
            by_vertical=facets["by_vertical"],
            by_country=facets["by_country"],
            by_language=facets["by_language"],
            by_platform=facets["by_platform"],
            by_placement=facets["by_placement"],
            by_domain=facets["by_domain"],
            by_advertiser=facets["by_advertiser"],
            by_cta=facets["by_cta"],
        )

    async def _read_facets(self, limit: int) -> dict[str, tuple[Facet, ...]]:
        facet_columns = (
            ("by_type", self._ads.ad_type),
            ("by_format", self._ads.format),
            ("by_vertical", self._ads.vertical),
            ("by_country", self._ads.country),
            ("by_language", self._ads.language),
            ("by_platform", self._ads.platform),
            ("by_placement", self._ads.placement),
            ("by_domain", self._ads.displayed_domain),
            ("by_advertiser", self._ads.advertiser),
            ("by_cta", self._ads.cta),
        )
        queries: list[Select[Any]] = []
        for position, (name, column) in enumerate(facet_columns):
            count = func.count().label("count")
            grouped = (
                select(column.label("value"), count)
                .select_from(self._ads)
                .where(column.is_not(None), column != "")
                .group_by(column)
                .order_by(count.desc())
                .limit(limit)
                .subquery()
            )
            queries.append(
                select(
                    literal(position).label("position"),
                    literal(name).label("facet"),
                    grouped.c.value,
                    grouped.c.count,
                )
            )
        combined = union_all(*queries).subquery()
        statement = select(
            combined.c.facet,
            combined.c.value,
            combined.c.count,
        ).order_by(combined.c.position, combined.c.count.desc())
        rows = (await self._session.execute(statement)).all()
        mutable: dict[str, list[Facet]] = {name: [] for name, _ in facet_columns}
        for name, value, count in rows:
            mutable[str(name)].append(Facet(value=str(value), count=int(count)))
        return {name: tuple(items) for name, items in mutable.items()}

    @staticmethod
    def _conditional_count(condition: Any) -> Any:
        return func.sum(case((condition, 1), else_=0))

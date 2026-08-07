from __future__ import annotations

from collections.abc import Sequence
from uuid import UUID

from sqlalchemy import ColumnElement, delete, func, or_, select, tuple_
from sqlalchemy.ext.asyncio import AsyncSession

from ...catalog import normalize_order
from ...models import Ad, AdPage, AdQuery
from .mapping import to_domain, to_record
from .models import FacebookAd


class SqlAlchemyAdRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def page(self, query: AdQuery) -> AdPage:
        filters = self._filters(query)
        field, descending = normalize_order(query.order_by)
        column = getattr(FacebookAd, field, FacebookAd.captured_at)
        ordering = column.desc() if descending else column
        statement = (
            select(FacebookAd)
            .where(*filters)
            .order_by(ordering)
            .offset(query.offset)
            .limit(query.page_size)
        )
        records = (await self._session.scalars(statement)).all()
        total = await self._session.scalar(
            select(func.count()).select_from(FacebookAd).where(*filters)
        )
        return AdPage(
            items=[to_domain(record) for record in records],
            total=int(total or 0),
            page=query.page,
            page_size=query.page_size,
        )

    async def get(self, ad_id: UUID) -> Ad | None:
        record = await self._session.scalar(
            select(FacebookAd).where(FacebookAd.id == ad_id)
        )
        return to_domain(record) if record is not None else None

    async def existing_identities(
        self,
        identities: set[tuple[str, str]],
    ) -> set[tuple[str, str]]:
        if not identities:
            return set()
        identity = tuple_(
            func.lower(func.trim(FacebookAd.country)),
            func.trim(FacebookAd.fb_ad_id),
        )
        statement = select(FacebookAd.country, FacebookAd.fb_ad_id).where(
            identity.in_(sorted(identities))
        )
        rows = (await self._session.execute(statement)).all()
        return {
            (country.strip().lower(), fb_ad_id.strip())
            for country, fb_ad_id in rows
            if country and fb_ad_id
        }

    async def add_many(self, ads: Sequence[Ad]) -> None:
        if not ads:
            return
        self._session.add_all(to_record(ad) for ad in ads)
        await self._session.flush()

    async def delete_run_ads(self, run_id: UUID) -> None:
        await self._session.execute(
            delete(FacebookAd).where(FacebookAd.run_id == run_id)
        )
        await self._session.flush()

    @staticmethod
    def _filters(query: AdQuery) -> list[ColumnElement[bool]]:
        filters: list[ColumnElement[bool]] = []
        equality = (
            (FacebookAd.run_id, query.run_id),
            (FacebookAd.format, query.format),
            (FacebookAd.vertical, query.vertical),
            (FacebookAd.country, query.country),
            (FacebookAd.language, query.language),
            (FacebookAd.platform, query.platform),
            (FacebookAd.placement, query.placement),
            (FacebookAd.cloaking, query.cloaking),
            (FacebookAd.has_video, query.has_video),
            (FacebookAd.screenshot_ok, query.screenshot_ok),
            (FacebookAd.fb_ad_id, query.fb_ad_id),
        )
        filters.extend(column == value for column, value in equality if value is not None)
        if query.ad_types:
            filters.append(FacebookAd.ad_type.in_(query.ad_types))
        if query.advertiser_search is not None:
            filters.append(FacebookAd.advertiser.ilike(f"%{query.advertiser_search}%"))
        if query.displayed_domain_search is not None:
            filters.append(
                FacebookAd.displayed_domain.ilike(
                    f"%{query.displayed_domain_search}%"
                )
            )
        if query.search:
            pattern = f"%{query.search}%"
            filters.append(
                or_(
                    FacebookAd.advertiser.ilike(pattern),
                    FacebookAd.displayed_domain.ilike(pattern),
                    FacebookAd.headline.ilike(pattern),
                    FacebookAd.ad_text.ilike(pattern),
                    FacebookAd.cta.ilike(pattern),
                    FacebookAd.landing_clean.ilike(pattern),
                )
            )
        if query.has_landing is True:
            filters.append(FacebookAd.landing_full.is_not(None))
        elif query.has_landing is False:
            filters.append(FacebookAd.landing_full.is_(None))
        return filters

from __future__ import annotations

from uuid import UUID

from sqlalchemy import ColumnElement, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from ...models import NewRun, Run, RunPage, RunQuery
from .mapping import to_domain, to_record
from .models import FacebookRun


class SqlAlchemyRunRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def page(self, query: RunQuery) -> RunPage:
        filters = self._filters(query)
        records = (
            await self._session.scalars(
                select(FacebookRun)
                .where(*filters)
                .order_by(FacebookRun.created_at.desc())
                .offset(query.offset)
                .limit(query.page_size)
            )
        ).all()
        total = await self._session.scalar(
            select(func.count()).select_from(FacebookRun).where(*filters)
        )
        return RunPage(
            items=tuple(to_domain(record) for record in records),
            total=int(total or 0),
            page=query.page,
            page_size=query.page_size,
        )

    async def get(self, run_id: UUID, *, refresh: bool = False) -> Run | None:
        statement = select(FacebookRun).where(FacebookRun.id == run_id)
        if refresh:
            statement = statement.execution_options(populate_existing=True)
        record = await self._session.scalar(statement)
        return None if record is None else to_domain(record)

    async def add(self, run: NewRun) -> Run:
        record = to_record(run)
        self._session.add(record)
        await self._session.flush()
        return to_domain(record)

    async def set_status(self, run_id: UUID, status: str) -> Run | None:
        record = await self._session.scalar(
            select(FacebookRun).where(FacebookRun.id == run_id)
        )
        if record is None:
            return None
        record.status = status
        await self._session.flush()
        await self._session.refresh(record)
        return to_domain(record)

    @staticmethod
    def _filters(query: RunQuery) -> list[ColumnElement[bool]]:
        filters: list[ColumnElement[bool]] = []
        if query.status is not None:
            filters.append(FacebookRun.status == query.status)
        if query.title_search is not None:
            filters.append(FacebookRun.title.ilike(f"%{query.title_search}%"))
        if query.octo_profile_uuid is not None:
            filters.append(FacebookRun.octo_profile_uuid == query.octo_profile_uuid)
        if query.profile_country is not None:
            filters.append(FacebookRun.profile_country == query.profile_country)
        return filters

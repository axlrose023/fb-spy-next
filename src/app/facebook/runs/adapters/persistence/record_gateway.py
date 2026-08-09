from __future__ import annotations

from collections.abc import Sequence
from typing import cast
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.sql.elements import ColumnElement

from .models import FacebookRun


class SqlAlchemyRunRecordGateway:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get_total_count(self, filters: list[ColumnElement[bool]]) -> int:
        statement = select(func.count()).select_from(FacebookRun).where(*filters)
        result = await self.session.execute(statement)
        return int(result.scalar() or 0)

    async def get_all(
        self,
        limit: int,
        offset: int,
        filters: list[ColumnElement[bool]],
    ) -> Sequence[FacebookRun]:
        statement = (
            select(FacebookRun)
            .where(*filters)
            .order_by(FacebookRun.created_at.desc())
            .offset(offset)
            .limit(limit)
        )
        result = await self.session.execute(statement)
        return cast(Sequence[FacebookRun], result.scalars().all())

    async def get_by_id(self, run_id: UUID) -> FacebookRun | None:
        result = await self.session.execute(
            select(FacebookRun).where(FacebookRun.id == run_id)
        )
        return cast(FacebookRun | None, result.scalar_one_or_none())

    async def create(self, run: FacebookRun) -> FacebookRun:
        self.session.add(run)
        await self.session.flush()
        return run

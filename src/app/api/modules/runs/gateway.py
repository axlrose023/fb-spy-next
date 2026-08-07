from collections.abc import Sequence
from uuid import UUID

from sqlalchemy import BinaryExpression, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.modules.runs.models import FacebookRun


class FacebookRunGateway:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def get_total_count(self, filters: list[BinaryExpression]) -> int:
        stmt = select(func.count()).select_from(FacebookRun).where(*filters)
        result = await self.session.execute(stmt)
        return result.scalar() or 0

    async def get_all(
        self,
        limit: int,
        offset: int,
        filters: list[BinaryExpression],
    ) -> Sequence[FacebookRun]:
        stmt = (
            select(FacebookRun)
            .where(*filters)
            .order_by(FacebookRun.created_at.desc())
            .offset(offset=offset)
            .limit(limit)
        )
        result = await self.session.execute(stmt)
        return result.scalars().all()

    async def get_by_id(self, run_id: UUID) -> FacebookRun | None:
        stmt = select(FacebookRun).where(FacebookRun.id == run_id)
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()

    async def create(self, run: FacebookRun) -> FacebookRun:
        self.session.add(run)
        await self.session.flush()
        return run

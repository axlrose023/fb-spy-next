from types import TracebackType
from typing import Self

from sqlalchemy.ext.asyncio import AsyncSession

from app.accounts.users.adapters.persistence import SqlAlchemyUserRecordGateway
from app.ad_library.ads.adapters.persistence import SqlAlchemyAdRepository
from app.facebook.runs.adapters.persistence import SqlAlchemyRunRecordGateway


class UnitOfWork:
    users: SqlAlchemyUserRecordGateway
    facebook_runs: SqlAlchemyRunRecordGateway
    facebook_ads: SqlAlchemyAdRepository

    def __init__(self, session: AsyncSession):
        self.session = session
        self.users = SqlAlchemyUserRecordGateway(session)
        self.facebook_runs = SqlAlchemyRunRecordGateway(session)
        self.facebook_ads = SqlAlchemyAdRepository(session)

    async def __aenter__(self) -> Self:
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc_val: BaseException | None,
        exc_tb: TracebackType | None,
    ) -> None:
        if exc_type is not None:
            await self.rollback()
        await self.session.close()

    async def commit(self: Self) -> None:
        await self.session.commit()

    async def flush(self: Self) -> None:
        await self.session.flush()

    async def refresh(self: Self, instance: object) -> None:
        await self.session.refresh(instance)

    async def rollback(self: Self) -> None:
        await self.session.rollback()

    async def close(self: Self) -> None:
        await self.session.close()

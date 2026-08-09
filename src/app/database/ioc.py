from collections.abc import AsyncIterator

from dishka import Provider, Scope, provide
from sqlalchemy.ext.asyncio import AsyncSession

from app.database.engine import SessionFactory
from app.database.uow import UnitOfWork


class DatabaseProvider(Provider):
    @provide(scope=Scope.REQUEST)
    async def get_session(self) -> AsyncIterator[AsyncSession]:
        async with SessionFactory() as session:
            yield session

    @provide(scope=Scope.REQUEST)
    async def get_uow(self, session: AsyncSession) -> AsyncIterator[UnitOfWork]:
        async with UnitOfWork(session) as uow:
            yield uow

from __future__ import annotations

import pytest
from dishka import make_async_container
from sqlalchemy.ext.asyncio import AsyncSession

from app.database.ioc import DatabaseProvider
from app.database.uow import UnitOfWork

pytestmark = pytest.mark.unit


@pytest.mark.asyncio
async def test_database_provider_shares_session_with_unit_of_work() -> None:
    container = make_async_container(DatabaseProvider())
    try:
        async with container() as request:
            session = await request.get(AsyncSession)
            uow = await request.get(UnitOfWork)

            assert uow.session is session
    finally:
        await container.close()

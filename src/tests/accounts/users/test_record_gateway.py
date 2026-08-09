from unittest.mock import create_autospec

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.accounts.users.adapters.persistence import (
    SqlAlchemyUserRecordGateway,
    UserRecord,
)
from app.api.modules.users.gateway import UserGateway
from app.database.uow import UnitOfWork

pytestmark = pytest.mark.unit


async def test_user_record_gateway_preserves_flush_only_writes() -> None:
    session = create_autospec(AsyncSession, instance=True)
    gateway = SqlAlchemyUserRecordGateway(session)
    record = UserRecord(username="user", password="hash", is_active=True)

    assert await gateway.create(record) is record
    assert await gateway.update(record) is record

    session.add.assert_called_once_with(record)
    assert session.flush.await_count == 2
    session.commit.assert_not_awaited()


def test_uow_and_legacy_path_use_owning_user_gateway() -> None:
    session = create_autospec(AsyncSession, instance=True)
    uow = UnitOfWork(session)

    assert type(uow.users) is SqlAlchemyUserRecordGateway
    assert UserGateway is SqlAlchemyUserRecordGateway

from unittest.mock import create_autospec

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.database.uow import UnitOfWork
from app.facebook.runs.adapters.persistence import (
    FacebookRun,
    SqlAlchemyRunRecordGateway,
)

pytestmark = pytest.mark.unit


async def test_run_record_gateway_preserves_flush_only_create() -> None:
    session = create_autospec(AsyncSession, instance=True)
    gateway = SqlAlchemyRunRecordGateway(session)
    record = FacebookRun(status="created", requested_minutes=10)

    assert await gateway.create(record) is record

    session.add.assert_called_once_with(record)
    session.flush.assert_awaited_once()
    session.commit.assert_not_awaited()


def test_uow_uses_owning_run_gateway() -> None:
    session = create_autospec(AsyncSession, instance=True)
    uow = UnitOfWork(session)

    assert type(uow.facebook_runs) is SqlAlchemyRunRecordGateway

from __future__ import annotations

from collections.abc import Sequence
from typing import cast
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.sql.elements import ColumnElement

from .models import UserRecord


class SqlAlchemyUserRecordGateway:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get_total_count(self, filters: list[ColumnElement[bool]]) -> int:
        statement = select(func.count()).select_from(UserRecord).where(*filters)
        result = await self.session.execute(statement)
        return cast(int, result.scalar())

    async def get_all(
        self,
        limit: int,
        offset: int,
        filters: list[ColumnElement[bool]],
    ) -> Sequence[UserRecord]:
        statement = select(UserRecord).filter(*filters).offset(offset).limit(limit)
        result = await self.session.execute(statement)
        return cast(Sequence[UserRecord], result.scalars().all())

    async def get_by_id(self, user_id: UUID) -> UserRecord | None:
        result = await self.session.execute(
            select(UserRecord).where(UserRecord.id == user_id)
        )
        return cast(UserRecord | None, result.scalar_one_or_none())

    async def get_by_username(self, username: str) -> UserRecord | None:
        result = await self.session.execute(
            select(UserRecord).where(UserRecord.username == username)
        )
        return cast(UserRecord | None, result.scalar_one_or_none())

    async def create(self, user: UserRecord) -> UserRecord:
        self.session.add(user)
        await self.session.flush()
        return user

    async def update(self, user: UserRecord) -> UserRecord:
        await self.session.flush()
        return user

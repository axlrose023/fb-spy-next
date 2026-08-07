from __future__ import annotations

from collections.abc import Sequence
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.sql.elements import ColumnElement

from ...models import NewUser, UserAccount, UserQuery, UserRole
from .models import UserRecord


class SqlAlchemyUserRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def list_users(self, query: UserQuery) -> Sequence[UserAccount]:
        statement = (
            select(UserRecord)
            .where(*self._filters(query))
            .offset(query.offset)
            .limit(query.page_size)
        )
        result = await self._session.execute(statement)
        return tuple(self._to_account(record) for record in result.scalars().all())

    async def count_users(self, query: UserQuery) -> int:
        statement = (
            select(func.count()).select_from(UserRecord).where(*self._filters(query))
        )
        result = await self._session.execute(statement)
        return int(result.scalar_one())

    async def get_by_id(self, user_id: UUID) -> UserAccount | None:
        return self._to_optional_account(await self._record_by_id(user_id))

    async def get_by_username(self, username: str) -> UserAccount | None:
        statement = select(UserRecord).where(UserRecord.username == username)
        result = await self._session.execute(statement)
        return self._to_optional_account(result.scalar_one_or_none())

    async def create(self, user: NewUser) -> UserAccount:
        record = UserRecord(
            username=user.username,
            password=user.password_hash,
            role=user.role.value,
            is_active=user.is_active,
        )
        self._session.add(record)
        await self._session.flush()
        await self._session.commit()
        return self._to_account(record)

    async def update(self, user: UserAccount) -> UserAccount | None:
        record = await self._record_by_id(user.id)
        if record is None:
            return None
        record.username = user.username
        record.password = user.password_hash
        record.role = user.role.value
        record.is_active = user.is_active
        await self._session.flush()
        await self._session.commit()
        return self._to_account(record)

    async def _record_by_id(self, user_id: UUID) -> UserRecord | None:
        statement = select(UserRecord).where(UserRecord.id == user_id)
        result = await self._session.execute(statement)
        return result.scalar_one_or_none()

    @staticmethod
    def _filters(query: UserQuery) -> list[ColumnElement[bool]]:
        filters: list[ColumnElement[bool]] = []
        if query.id is not None:
            filters.append(UserRecord.id == query.id)
        if query.username is not None:
            filters.append(UserRecord.username == query.username)
        if query.username_search is not None:
            filters.append(UserRecord.username.ilike(f"%{query.username_search}%"))
        if query.role is not None:
            filters.append(UserRecord.role == query.role.value)
        return filters

    @classmethod
    def _to_optional_account(cls, record: UserRecord | None) -> UserAccount | None:
        return None if record is None else cls._to_account(record)

    @staticmethod
    def _to_account(record: UserRecord) -> UserAccount:
        return UserAccount(
            id=record.id,
            username=record.username,
            password_hash=record.password,
            role=UserRole(record.role),
            is_active=record.is_active,
        )

from __future__ import annotations

from dataclasses import replace
from uuid import uuid4

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.accounts.users.adapters.persistence import SqlAlchemyUserRepository
from app.accounts.users.models import NewUser, UserQuery, UserRole

pytestmark = pytest.mark.integration


async def test_repository_round_trip_filters_and_updates(
    session: AsyncSession,
) -> None:
    repository = SqlAlchemyUserRepository(session)
    marker = "repository-stage-two"
    member = await repository.create(
        NewUser(
            username=f"{marker}-member",
            password_hash="member-hash",
            role=UserRole.USER,
        )
    )
    await repository.create(
        NewUser(
            username=f"{marker}-admin",
            password_hash="admin-hash",
            role=UserRole.ADMIN,
        )
    )

    query = UserQuery(
        page=1,
        page_size=10,
        username_search=marker,
        role=UserRole.USER,
    )
    listed = await repository.list_users(query)

    assert [item.id for item in listed] == [member.id]
    assert await repository.count_users(query) == 1
    assert await repository.get_by_username(member.username) == member
    assert await repository.get_by_id(member.id) == member
    assert await repository.get_by_id(uuid4()) is None

    exact = await repository.list_users(
        UserQuery(
            page=1,
            page_size=10,
            id=member.id,
            username=member.username,
        )
    )
    assert exact == (member,)

    updated = await repository.update(
        replace(
            member,
            username=f"{marker}-renamed",
            password_hash="new-hash",
            role=UserRole.ADMIN,
            is_active=False,
        )
    )

    assert updated is not None
    assert updated.username == f"{marker}-renamed"
    assert updated.password_hash == "new-hash"
    assert updated.role is UserRole.ADMIN
    assert updated.is_active is False
    assert await repository.update(replace(member, id=uuid4())) is None

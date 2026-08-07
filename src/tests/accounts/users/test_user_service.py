from __future__ import annotations

from dataclasses import dataclass
from uuid import UUID, uuid4

import pytest

from app.accounts.users.exceptions import (
    AdminRequired,
    OwnAccountRequired,
    PrivilegedFieldsRequireAdmin,
    UsernameTaken,
    UserNotFound,
)
from app.accounts.users.models import (
    CreateUser,
    NewUser,
    UpdateUser,
    UserAccount,
    UserQuery,
    UserRole,
)
from app.accounts.users.service import UserService

pytestmark = pytest.mark.unit


@dataclass(frozen=True)
class Actor:
    id: UUID
    is_admin: bool


class StubHasher:
    def hash(self, password: str) -> str:
        return f"hashed:{password}"


class MemoryUsers:
    def __init__(self, *accounts: UserAccount) -> None:
        self.accounts = {account.id: account for account in accounts}
        self.drop_during_update = False

    async def list_users(self, query: UserQuery) -> list[UserAccount]:
        return list(self.accounts.values())[
            query.offset : query.offset + query.page_size
        ]

    async def count_users(self, _query: UserQuery) -> int:
        return len(self.accounts)

    async def get_by_id(self, user_id: UUID) -> UserAccount | None:
        return self.accounts.get(user_id)

    async def get_by_username(self, username: str) -> UserAccount | None:
        return next(
            (
                account
                for account in self.accounts.values()
                if account.username == username
            ),
            None,
        )

    async def create(self, user: NewUser) -> UserAccount:
        account = UserAccount(
            id=uuid4(),
            username=user.username,
            password_hash=user.password_hash,
            role=user.role,
            is_active=user.is_active,
        )
        self.accounts[account.id] = account
        return account

    async def update(self, user: UserAccount) -> UserAccount | None:
        if self.drop_during_update:
            return None
        self.accounts[user.id] = user
        return user


def account(
    *,
    username: str = "member",
    role: UserRole = UserRole.USER,
    active: bool = True,
) -> UserAccount:
    return UserAccount(
        id=uuid4(),
        username=username,
        password_hash="old-hash",
        role=role,
        is_active=active,
    )


def service(repository: MemoryUsers) -> UserService:
    return UserService(repository, StubHasher())


async def test_list_and_get_return_public_users() -> None:
    first = account(username="first")
    second = account(username="second")
    users = MemoryUsers(first, second)

    page = await service(users).list_users(UserQuery(page=1, page_size=1))
    found = await service(users).get_user(second.id)

    assert page.total == 2
    assert [item.username for item in page.items] == ["first"]
    assert found.username == "second"
    assert found.is_admin is False
    assert not hasattr(found, "password_hash")


async def test_get_missing_user_raises_domain_error() -> None:
    with pytest.raises(UserNotFound):
        await service(MemoryUsers()).get_user(uuid4())


async def test_admin_creates_user_with_hashed_password() -> None:
    users = MemoryUsers()

    created = await service(users).create_user(
        CreateUser("created", "plain", UserRole.ADMIN),
        Actor(uuid4(), is_admin=True),
    )

    stored = await users.get_by_id(created.id)
    assert stored is not None
    assert stored.password_hash == "hashed:plain"
    assert stored.role is UserRole.ADMIN


async def test_create_requires_admin_and_unique_username() -> None:
    existing = account(username="occupied")

    with pytest.raises(AdminRequired):
        await service(MemoryUsers()).create_user(
            CreateUser("new", "password"),
            Actor(uuid4(), is_admin=False),
        )
    with pytest.raises(UsernameTaken):
        await service(MemoryUsers(existing)).create_user(
            CreateUser("occupied", "password"),
            Actor(uuid4(), is_admin=True),
        )


async def test_user_can_change_own_username_and_password() -> None:
    existing = account(username="before")
    users = MemoryUsers(existing)

    updated = await service(users).update_user(
        existing.id,
        UpdateUser(username="after", password="new-password"),
        Actor(existing.id, is_admin=False),
    )

    stored = await users.get_by_id(existing.id)
    assert updated.username == "after"
    assert stored is not None
    assert stored.password_hash == "hashed:new-password"


async def test_regular_user_update_permissions_are_checked_before_lookup() -> None:
    actor = Actor(uuid4(), is_admin=False)

    with pytest.raises(OwnAccountRequired):
        await service(MemoryUsers()).update_user(
            uuid4(),
            UpdateUser(username="forbidden"),
            actor,
        )
    with pytest.raises(PrivilegedFieldsRequireAdmin):
        await service(MemoryUsers()).update_user(
            actor.id,
            UpdateUser(is_active=False),
            actor,
        )


async def test_admin_can_update_privileged_fields() -> None:
    existing = account()
    users = MemoryUsers(existing)

    updated = await service(users).update_user(
        existing.id,
        UpdateUser(role=UserRole.ADMIN, is_active=False),
        Actor(uuid4(), is_admin=True),
    )

    assert updated.role is UserRole.ADMIN
    assert updated.is_active is False


async def test_update_rejects_duplicate_and_disappeared_user() -> None:
    existing = account(username="existing")
    occupied = account(username="occupied")
    users = MemoryUsers(existing, occupied)
    admin = Actor(uuid4(), is_admin=True)

    with pytest.raises(UsernameTaken):
        await service(users).update_user(
            existing.id,
            UpdateUser(username="occupied"),
            admin,
        )

    users.drop_during_update = True
    with pytest.raises(UserNotFound):
        await service(users).update_user(existing.id, UpdateUser(), admin)

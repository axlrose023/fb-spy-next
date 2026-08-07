from __future__ import annotations

from collections.abc import Sequence
from typing import Protocol
from uuid import UUID

from .models import NewUser, UserAccount, UserQuery


class UserActor(Protocol):
    @property
    def id(self) -> UUID: ...

    @property
    def is_admin(self) -> bool: ...


class PasswordHasher(Protocol):
    def hash(self, password: str) -> str: ...


class UserRepository(Protocol):
    async def list_users(self, query: UserQuery) -> Sequence[UserAccount]: ...

    async def count_users(self, query: UserQuery) -> int: ...

    async def get_by_id(self, user_id: UUID) -> UserAccount | None: ...

    async def get_by_username(self, username: str) -> UserAccount | None: ...

    async def create(self, user: NewUser) -> UserAccount: ...

    async def update(self, user: UserAccount) -> UserAccount | None: ...

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from uuid import UUID


class UserRole(StrEnum):
    ADMIN = "admin"
    USER = "user"


@dataclass(frozen=True, slots=True)
class User:
    id: UUID
    username: str
    role: UserRole
    is_active: bool

    @property
    def is_admin(self) -> bool:
        return self.role is UserRole.ADMIN


@dataclass(frozen=True, slots=True)
class UserAccount:
    id: UUID
    username: str
    password_hash: str = field(repr=False)
    role: UserRole
    is_active: bool

    def as_user(self) -> User:
        return User(
            id=self.id,
            username=self.username,
            role=self.role,
            is_active=self.is_active,
        )


@dataclass(frozen=True, slots=True)
class NewUser:
    username: str
    password_hash: str = field(repr=False)
    role: UserRole
    is_active: bool = True


@dataclass(frozen=True, slots=True)
class CreateUser:
    username: str
    password: str = field(repr=False)
    role: UserRole = UserRole.USER


@dataclass(frozen=True, slots=True)
class UpdateUser:
    username: str | None = None
    password: str | None = field(default=None, repr=False)
    role: UserRole | None = None
    is_active: bool | None = None

    @property
    def changes_privileged_fields(self) -> bool:
        return self.role is not None or self.is_active is not None


@dataclass(frozen=True, slots=True)
class UserQuery:
    page: int
    page_size: int
    id: UUID | None = None
    username: str | None = None
    username_search: str | None = None
    role: UserRole | None = None

    @property
    def offset(self) -> int:
        return (self.page - 1) * self.page_size


@dataclass(frozen=True, slots=True)
class UserPage:
    items: tuple[User, ...]
    total: int
    page: int
    page_size: int

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from uuid import UUID


class TokenKind(StrEnum):
    ACCESS = "access"
    REFRESH = "refresh"


@dataclass(frozen=True, slots=True)
class Credentials:
    username: str
    password: str = field(repr=False)


@dataclass(frozen=True, slots=True)
class AuthUser:
    id: UUID
    username: str
    password_hash: str = field(repr=False)
    role: str
    is_active: bool

    def as_current_user(self) -> CurrentUser:
        return CurrentUser(
            id=self.id,
            username=self.username,
            role=self.role,
            is_active=self.is_active,
        )


@dataclass(frozen=True, slots=True)
class CurrentUser:
    id: UUID
    username: str
    role: str
    is_active: bool

    @property
    def is_admin(self) -> bool:
        return self.role == "admin"


@dataclass(frozen=True, slots=True)
class TokenClaims:
    user_id: UUID
    kind: TokenKind


@dataclass(frozen=True, slots=True)
class TokenPair:
    access_token: str
    refresh_token: str
    expires_in: int
    refresh_expires_in: int
    token_type: str = "bearer"

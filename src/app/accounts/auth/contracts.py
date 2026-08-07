from __future__ import annotations

from typing import Protocol
from uuid import UUID

from .models import AuthUser, TokenClaims, TokenPair


class UserReader(Protocol):
    async def get_by_username(self, username: str) -> AuthUser | None: ...

    async def get_by_id(self, user_id: UUID) -> AuthUser | None: ...


class TokenCodec(Protocol):
    def create_pair(self, user_id: UUID) -> TokenPair: ...

    def decode_access(self, token: str) -> TokenClaims: ...

    def decode_refresh(self, token: str) -> TokenClaims: ...


class PasswordVerifier(Protocol):
    def verify(self, password: str, password_hash: str) -> bool: ...

    def hash(self, password: str) -> str: ...

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID

import jwt
from jwt import ExpiredSignatureError, InvalidTokenError

from ..exceptions import (
    InvalidAccessToken,
    InvalidRefreshToken,
    InvalidRefreshTokenPayload,
    InvalidRefreshTokenType,
    RefreshTokenExpired,
)
from ..models import TokenClaims, TokenKind, TokenPair


def utc_now() -> datetime:
    return datetime.now(UTC)


class JwtTokenCodec:
    def __init__(
        self,
        *,
        secret_key: str,
        algorithm: str,
        access_ttl: timedelta,
        refresh_ttl: timedelta,
        clock: Callable[[], datetime] = utc_now,
    ) -> None:
        self._secret_key = secret_key
        self._algorithm = algorithm
        self._access_ttl = access_ttl
        self._refresh_ttl = refresh_ttl
        self._clock = clock

    def create_pair(self, user_id: UUID) -> TokenPair:
        access_token = self._encode(user_id, TokenKind.ACCESS, self._access_ttl)
        refresh_token = self._encode(user_id, TokenKind.REFRESH, self._refresh_ttl)
        return TokenPair(
            access_token=access_token,
            refresh_token=refresh_token,
            expires_in=int(self._access_ttl.total_seconds()),
            refresh_expires_in=int(self._refresh_ttl.total_seconds()),
        )

    def decode_access(self, token: str) -> TokenClaims:
        try:
            payload = self._decode(token)
            return self._claims(payload, TokenKind.ACCESS)
        except (
            ExpiredSignatureError,
            InvalidTokenError,
            KeyError,
            TypeError,
            ValueError,
        ):
            raise InvalidAccessToken from None

    def decode_refresh(self, token: str) -> TokenClaims:
        payload = self.decode_refresh_payload(token)
        try:
            return self._claims(payload, TokenKind.REFRESH)
        except (KeyError, TypeError, ValueError):
            raise InvalidRefreshTokenPayload from None

    def decode_refresh_payload(self, token: str) -> dict[str, Any]:
        try:
            payload = self._decode(token)
        except ExpiredSignatureError:
            raise RefreshTokenExpired from None
        except InvalidTokenError:
            raise InvalidRefreshToken from None

        if payload.get("type") != TokenKind.REFRESH.value:
            raise InvalidRefreshTokenType
        return payload

    def _encode(self, user_id: UUID, kind: TokenKind, ttl: timedelta) -> str:
        payload = {
            "sub": str(user_id),
            "type": kind.value,
            "exp": int((self._clock() + ttl).timestamp()),
        }
        return jwt.encode(payload, self._secret_key, algorithm=self._algorithm)

    def _decode(self, token: str) -> dict[str, Any]:
        return jwt.decode(
            token,
            self._secret_key,
            algorithms=[self._algorithm],
        )

    @staticmethod
    def _claims(payload: dict[str, Any], expected: TokenKind) -> TokenClaims:
        if payload.get("type") != expected.value:
            raise ValueError("invalid token type")
        return TokenClaims(user_id=UUID(payload["sub"]), kind=expected)

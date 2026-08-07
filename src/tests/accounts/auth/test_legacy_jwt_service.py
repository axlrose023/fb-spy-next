from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import uuid4

import jwt
import pytest
from fastapi import HTTPException

from app.api.modules.auth.services import JwtService
from app.api.modules.users.models import User, UserRole
from app.settings import Config, get_config

pytestmark = pytest.mark.unit


class StubUsers:
    def __init__(self, user: User | None) -> None:
        self.user = user

    async def get_by_id(self, _user_id: object) -> User | None:
        return self.user


class StubUnitOfWork:
    def __init__(self, user: User | None) -> None:
        self.users = StubUsers(user)


def build_user(*, active: bool = True) -> User:
    user = User(
        username="jwt-user",
        password="unused-hash",
        role=UserRole.USER.value,
        is_active=active,
    )
    user.id = uuid4()
    return user


def encode(config: Config, payload: dict[str, Any]) -> str:
    return jwt.encode(
        payload,
        config.jwt.secret_key,
        algorithm=config.jwt.algorithm,
    )


def assert_http_error(raised: pytest.ExceptionInfo[HTTPException], detail: str) -> None:
    assert raised.value.status_code == 401
    assert raised.value.detail == detail


def test_token_pair_contains_expected_claims_and_expirations() -> None:
    config = get_config()
    user = build_user()

    pair = JwtService(config).create_token_pair(user)
    access = jwt.decode(
        pair.access_token,
        config.jwt.secret_key,
        algorithms=[config.jwt.algorithm],
    )
    refresh = jwt.decode(
        pair.refresh_token,
        config.jwt.secret_key,
        algorithms=[config.jwt.algorithm],
    )

    assert access["sub"] == refresh["sub"] == str(user.id)
    assert access["type"] == "access"
    assert refresh["type"] == "refresh"
    assert pair.expires_in == config.jwt.access_token_expires_in_minutes * 60
    assert pair.refresh_expires_in == config.jwt.refresh_expires_in_minutes * 60


def test_refresh_validation_distinguishes_expired_token() -> None:
    config = get_config()
    token = encode(
        config,
        {
            "sub": str(uuid4()),
            "type": "refresh",
            "exp": datetime.now(UTC) - timedelta(seconds=1),
        },
    )

    with pytest.raises(HTTPException) as raised:
        JwtService(config).validate_refresh_token(token)

    assert_http_error(raised, "Refresh token expired")


def test_refresh_validation_distinguishes_invalid_signature() -> None:
    config = get_config()
    token = jwt.encode(
        {"sub": str(uuid4()), "type": "refresh"},
        "different-test-secret-with-at-least-32-bytes",
        algorithm=config.jwt.algorithm,
    )

    with pytest.raises(HTTPException) as raised:
        JwtService(config).validate_refresh_token(token)

    assert_http_error(raised, "Invalid refresh token")


def test_refresh_validation_distinguishes_wrong_token_type() -> None:
    config = get_config()
    token = encode(config, {"sub": str(uuid4()), "type": "access"})

    with pytest.raises(HTTPException) as raised:
        JwtService(config).validate_refresh_token(token)

    assert_http_error(raised, "Invalid refresh token type")


async def test_refresh_distinguishes_invalid_payload() -> None:
    config = get_config()
    token = encode(config, {"type": "refresh"})

    with pytest.raises(HTTPException) as raised:
        await JwtService(config).refresh(
            token,
            StubUnitOfWork(build_user()),  # type: ignore[arg-type]
        )

    assert_http_error(raised, "Invalid refresh token payload")


@pytest.mark.parametrize("user", [None, build_user(active=False)])
async def test_refresh_rejects_unavailable_user(user: User | None) -> None:
    config = get_config()
    token = JwtService(config).create_token_pair(build_user()).refresh_token

    with pytest.raises(HTTPException) as raised:
        await JwtService(config).refresh(
            token,
            StubUnitOfWork(user),  # type: ignore[arg-type]
        )

    assert raised.value.status_code == 403
    assert raised.value.detail == "User is not allowed"

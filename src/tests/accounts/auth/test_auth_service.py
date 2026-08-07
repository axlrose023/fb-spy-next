from __future__ import annotations

from datetime import timedelta
from uuid import uuid4

import bcrypt
import pytest
from fastapi import HTTPException

from app.accounts.auth import AuthenticateUser, AuthService
from app.accounts.auth.adapters import BcryptPasswordVerifier, JwtTokenCodec
from app.accounts.auth.exceptions import (
    InvalidAccessToken,
    InvalidCredentials,
    UserNotAllowed,
)
from app.accounts.auth.models import AuthUser, Credentials
from app.settings import Config, get_config

pytestmark = pytest.mark.unit

PASSWORD = "correct-password"
PASSWORD_HASH = bcrypt.hashpw(PASSWORD.encode(), bcrypt.gensalt(rounds=4)).decode()


class StubUsers:
    def __init__(self, user: AuthUser | None) -> None:
        self.user = user

    async def get_by_username(self, _username: str) -> AuthUser | None:
        return self.user

    async def get_by_id(self, _user_id: object) -> AuthUser | None:
        return self.user


def build_user(*, active: bool = True) -> AuthUser:
    return AuthUser(
        id=uuid4(),
        username="characterized-user",
        password_hash=PASSWORD_HASH,
        role="user",
        is_active=active,
    )


def build_codec(config: Config) -> JwtTokenCodec:
    return JwtTokenCodec(
        secret_key=config.jwt.secret_key,
        algorithm=config.jwt.algorithm,
        access_ttl=timedelta(minutes=config.jwt.access_token_expires_in_minutes),
        refresh_ttl=timedelta(minutes=config.jwt.refresh_expires_in_minutes),
    )


def build_service(user: AuthUser | None, config: Config) -> AuthService:
    return AuthService(
        StubUsers(user),
        build_codec(config),
        BcryptPasswordVerifier(rounds=4),
    )


async def test_login_returns_bearer_token_pair() -> None:
    config = get_config()
    user = build_user()

    result = await build_service(user, config).login(
        Credentials(username=user.username, password=PASSWORD)
    )

    assert result.token_type == "bearer"
    assert result.expires_in == config.jwt.access_token_expires_in_minutes * 60
    assert result.refresh_expires_in == config.jwt.refresh_expires_in_minutes * 60


@pytest.mark.parametrize("user", [None, build_user(active=False)])
async def test_login_hides_missing_and_disabled_users(user: AuthUser | None) -> None:
    with pytest.raises(InvalidCredentials):
        await build_service(user, get_config()).login(
            Credentials(username="characterized-user", password=PASSWORD)
        )


async def test_login_rejects_wrong_password_with_same_error() -> None:
    with pytest.raises(InvalidCredentials):
        await build_service(build_user(), get_config()).login(
            Credentials(username="characterized-user", password="wrong-password")
        )


async def test_access_authentication_returns_active_user() -> None:
    config = get_config()
    user = build_user()
    service = build_service(user, config)
    token = build_codec(config).create_pair(user.id).access_token

    result = await AuthenticateUser().get_current_user(
        service=service,
        token=token,
    )

    assert result.id == user.id
    assert result.username == user.username


@pytest.mark.parametrize("user", [None, build_user(active=False)])
async def test_access_authentication_hides_unavailable_user(
    user: AuthUser | None,
) -> None:
    config = get_config()
    token = build_codec(config).create_pair(build_user().id).access_token

    with pytest.raises(HTTPException) as raised:
        await AuthenticateUser().get_current_user(
            service=build_service(user, config),
            token=token,
        )

    assert raised.value.status_code == 401
    assert raised.value.detail == "Could not validate credentials"
    assert raised.value.headers == {"WWW-Authenticate": "Bearer"}


async def test_service_uses_one_error_for_any_invalid_access_token() -> None:
    with pytest.raises(InvalidAccessToken):
        await build_service(build_user(), get_config()).authenticate("not-a-jwt")


async def test_refresh_issues_new_pair_for_active_user() -> None:
    config = get_config()
    user = build_user()
    token = build_codec(config).create_pair(user.id).refresh_token

    pair = await build_service(user, config).refresh(token)

    assert pair.access_token
    assert pair.refresh_token


@pytest.mark.parametrize("user", [None, build_user(active=False)])
async def test_refresh_rejects_unavailable_user(user: AuthUser | None) -> None:
    config = get_config()
    token = build_codec(config).create_pair(build_user().id).refresh_token

    with pytest.raises(UserNotAllowed):
        await build_service(user, config).refresh(token)


def test_hash_password_delegates_to_password_adapter() -> None:
    hashed = build_service(build_user(), get_config()).hash_password(PASSWORD)

    assert hashed != PASSWORD
    assert bcrypt.checkpw(PASSWORD.encode(), hashed.encode())

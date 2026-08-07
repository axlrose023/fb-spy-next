from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import uuid4

import bcrypt
import jwt
import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.accounts.users import UserRole
from app.accounts.users.adapters.persistence import UserRecord
from app.settings import Config, get_config

pytestmark = pytest.mark.integration


def password_hash(password: str) -> str:
    return bytes(bcrypt.hashpw(password.encode(), bcrypt.gensalt(rounds=4))).decode()


async def persist_user(
    session: AsyncSession,
    *,
    username: str,
    password: str,
    active: bool = True,
) -> UserRecord:
    user = UserRecord(
        username=username,
        password=password_hash(password),
        role=UserRole.USER.value,
        is_active=active,
    )
    session.add(user)
    await session.commit()
    return user


async def test_login_and_refresh_keep_public_response_shape(
    client: AsyncClient,
    session: AsyncSession,
) -> None:
    username = f"auth-{uuid4()}"
    password = "api-password"
    await persist_user(session, username=username, password=password)

    login = await client.post(
        "/auth/login",
        json={"username": username, "password": password},
    )

    assert login.status_code == 200
    pair = login.json()
    assert set(pair) == {
        "access_token",
        "refresh_token",
        "token_type",
        "expires_in",
        "refresh_expires_in",
    }
    assert pair["token_type"] == "bearer"

    refresh = await client.post(
        "/auth/refresh",
        json={"refresh_token": pair["refresh_token"]},
    )
    assert refresh.status_code == 200
    assert set(refresh.json()) == set(pair)


@pytest.mark.parametrize("active", [True, False])
async def test_login_uses_same_error_for_bad_credentials(
    client: AsyncClient,
    session: AsyncSession,
    active: bool,
) -> None:
    username = f"auth-failure-{uuid4()}"
    password = "api-password"
    await persist_user(
        session,
        username=username,
        password=password,
        active=active,
    )

    response = await client.post(
        "/auth/login",
        json={
            "username": username if not active else f"missing-{uuid4()}",
            "password": "wrong-password",
        },
    )

    assert response.status_code == 401
    assert response.json() == {"detail": "Incorrect username or password"}


async def test_protected_route_rejects_refresh_token(
    client: AsyncClient,
    session: AsyncSession,
) -> None:
    username = f"auth-protected-{uuid4()}"
    password = "api-password"
    await persist_user(session, username=username, password=password)
    pair = (
        await client.post(
            "/auth/login",
            json={"username": username, "password": password},
        )
    ).json()

    response = await client.get(
        "/users/me",
        headers={"Authorization": f"Bearer {pair['refresh_token']}"},
    )

    assert response.status_code == 401
    assert response.json() == {"detail": "Could not validate credentials"}
    assert response.headers["www-authenticate"] == "Bearer"


def encode_token(
    config: Config, payload: dict[str, Any], *, secret: str | None = None
) -> str:
    return str(
        jwt.encode(
            payload,
            secret or config.jwt.secret_key,
            algorithm=config.jwt.algorithm,
        )
    )


@pytest.mark.parametrize(
    ("payload", "expected_detail"),
    [
        ({"sub": "invalid-uuid", "type": "refresh"}, "Invalid refresh token payload"),
        ({"sub": str(uuid4()), "type": "access"}, "Invalid refresh token type"),
        (
            {
                "sub": str(uuid4()),
                "type": "refresh",
                "exp": datetime.now(UTC) - timedelta(seconds=1),
            },
            "Refresh token expired",
        ),
    ],
)
async def test_refresh_preserves_specific_token_errors(
    client: AsyncClient,
    payload: dict[str, Any],
    expected_detail: str,
) -> None:
    token = encode_token(get_config(), payload)

    response = await client.post(
        "/auth/refresh",
        json={"refresh_token": token},
    )

    assert response.status_code == 401
    assert response.json() == {"detail": expected_detail}


async def test_refresh_rejects_invalid_signature(client: AsyncClient) -> None:
    config = get_config()
    token = encode_token(
        config,
        {"sub": str(uuid4()), "type": "refresh"},
        secret="different-test-secret-with-at-least-32-bytes",
    )

    response = await client.post(
        "/auth/refresh",
        json={"refresh_token": token},
    )

    assert response.status_code == 401
    assert response.json() == {"detail": "Invalid refresh token"}


async def test_refresh_rejects_user_disabled_after_login(
    client: AsyncClient,
    session: AsyncSession,
) -> None:
    username = f"auth-disabled-refresh-{uuid4()}"
    password = "api-password"
    user = await persist_user(session, username=username, password=password)
    pair = (
        await client.post(
            "/auth/login",
            json={"username": username, "password": password},
        )
    ).json()
    user.is_active = False
    await session.commit()

    response = await client.post(
        "/auth/refresh",
        json={"refresh_token": pair["refresh_token"]},
    )

    assert response.status_code == 403
    assert response.json() == {"detail": "User is not allowed"}


async def test_protected_route_hides_malformed_signed_subject(
    client: AsyncClient,
) -> None:
    token = encode_token(
        get_config(),
        {"sub": "invalid-uuid", "type": "access"},
    )

    response = await client.get(
        "/users/me",
        headers={"Authorization": f"Bearer {token}"},
    )

    assert response.status_code == 401
    assert response.json() == {"detail": "Could not validate credentials"}

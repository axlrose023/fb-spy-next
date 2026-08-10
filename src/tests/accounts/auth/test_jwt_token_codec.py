from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import uuid4

import jwt
import pytest

from app.accounts.auth.adapters import JwtTokenCodec
from app.accounts.auth.exceptions import (
    InvalidRefreshToken,
    InvalidRefreshTokenPayload,
    InvalidRefreshTokenType,
    RefreshTokenExpired,
)
from app.settings import Config, get_config

pytestmark = pytest.mark.unit


def build_codec(config: Config) -> JwtTokenCodec:
    return JwtTokenCodec(
        secret_key=config.jwt.secret_key,
        algorithm=config.jwt.algorithm,
        access_ttl=timedelta(minutes=config.jwt.access_token_expires_in_minutes),
        refresh_ttl=timedelta(minutes=config.jwt.refresh_expires_in_minutes),
    )


def encode(config: Config, payload: dict[str, Any]) -> str:
    return str(
        jwt.encode(
            payload,
            config.jwt.secret_key,
            algorithm=config.jwt.algorithm,
        )
    )


def test_token_pair_contains_expected_claims_and_expirations() -> None:
    config = get_config()
    user_id = uuid4()

    pair = build_codec(config).create_pair(user_id)
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

    assert access["sub"] == refresh["sub"] == str(user_id)
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

    with pytest.raises(RefreshTokenExpired):
        build_codec(config).decode_refresh_payload(token)


def test_refresh_validation_distinguishes_invalid_signature() -> None:
    config = get_config()
    token = jwt.encode(
        {"sub": str(uuid4()), "type": "refresh"},
        "different-test-secret-with-at-least-32-bytes",
        algorithm=config.jwt.algorithm,
    )

    with pytest.raises(InvalidRefreshToken):
        build_codec(config).decode_refresh_payload(token)


def test_refresh_validation_distinguishes_wrong_token_type() -> None:
    config = get_config()
    token = encode(config, {"sub": str(uuid4()), "type": "access"})

    with pytest.raises(InvalidRefreshTokenType):
        build_codec(config).decode_refresh_payload(token)


def test_refresh_validation_rejects_missing_subject() -> None:
    config = get_config()
    token = encode(config, {"type": "refresh"})

    with pytest.raises(InvalidRefreshTokenPayload):
        build_codec(config).decode_refresh(token)

from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys

import pytest

from app.accounts.settings import JwtConfig as OwnedJwtConfig
from app.ad_library.media.settings import MediaStorageConfig as OwnedMediaConfig
from app.api.settings import APIConfig as OwnedAPIConfig
from app.browser.settings import (
    PlaywrightConfig as OwnedPlaywrightConfig,
)
from app.browser.settings import (
    UserAgentConfig as OwnedUserAgentConfig,
)
from app.browser.settings import ViewportConfig as OwnedViewportConfig
from app.clients.settings import GeminiConfig as OwnedGeminiConfig
from app.database.settings import PostgresConfig as OwnedPostgresConfig
from app.database.settings import RedisConfig as OwnedRedisConfig
from app.facebook.settings import FacebookConfig as OwnedFacebookConfig
from app.settings import (
    APIConfig,
    Config,
    FacebookConfig,
    GeminiConfig,
    JwtConfig,
    MediaStorageConfig,
    PlaywrightConfig,
    PostgresConfig,
    RedisConfig,
    UserAgentConfig,
    ViewportConfig,
)

pytestmark = pytest.mark.unit


def test_root_settings_reexport_owning_models() -> None:
    assert APIConfig is OwnedAPIConfig
    assert JwtConfig is OwnedJwtConfig
    assert MediaStorageConfig is OwnedMediaConfig
    assert PostgresConfig is OwnedPostgresConfig
    assert RedisConfig is OwnedRedisConfig
    assert PlaywrightConfig is OwnedPlaywrightConfig
    assert ViewportConfig is OwnedViewportConfig
    assert UserAgentConfig is OwnedUserAgentConfig
    assert FacebookConfig is OwnedFacebookConfig
    assert GeminiConfig is OwnedGeminiConfig


def test_default_config_contract() -> None:
    payload = Config(_env_file=None).model_dump(mode="json", exclude={"paths"})
    payload["facebook"]["runner_python"] = "<python>"
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()

    assert hashlib.sha256(encoded).hexdigest() == (
        "aa3add1e571515b7b99216694b784f838ed70fe5f0cd6be2dc0ab79bf11cfabd"
    )


def test_nested_environment_names_are_unchanged(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    for name in list(os.environ):
        if name.startswith("APP__"):
            monkeypatch.delenv(name)
    values = {
        "APP__ENV": "dev",
        "APP__API__PORT": "9001",
        "APP__JWT__ALGORITHM": "HS512",
        "APP__MEDIA__UPLOAD_CONCURRENCY": "7",
        "APP__POSTGRES__HOST": "db.internal",
        "APP__REDIS__DB": "4",
        "APP__PLAYWRIGHT__MAX_BROWSERS": "3",
        "APP__VIEWPORT__WIDTH_MIN": "1024",
        "APP__USERAGENT__FALLBACK": "test-agent",
        "APP__FACEBOOK__DEFAULT_COUNTRY": "Canada",
        "APP__GEMINI__MODEL": "test-model",
    }
    for name, value in values.items():
        monkeypatch.setenv(name, value)

    config = Config(_env_file=None)

    assert config.env == "dev"
    assert config.api.port == 9001
    assert config.jwt.algorithm == "HS512"
    assert config.media.upload_concurrency == 7
    assert config.postgres.host == "db.internal"
    assert config.redis.db == 4
    assert config.playwright.max_browsers == 3
    assert config.viewport.width_min == 1024
    assert config.useragent.fallback == "test-agent"
    assert config.facebook.default_country == "Canada"
    assert config.gemini.model == "test-model"


def test_lazy_package_exports_preserve_public_objects() -> None:
    from app.browser import browser_provider
    from app.browser.ioc import browser_provider as owned_browser_provider
    from app.clients import HttpClient, HttpClientsProvider
    from app.clients.base import HttpClient as OwnedHttpClient
    from app.clients.providers import HttpClientsProvider as OwnedHttpClientsProvider

    assert browser_provider is owned_browser_provider
    assert HttpClient is OwnedHttpClient
    assert HttpClientsProvider is OwnedHttpClientsProvider


@pytest.mark.parametrize(
    "source",
    [
        "from app.browser import browser_provider; from app.settings import Config",
        "from app.clients import HttpClientsProvider; from app.settings import Config",
    ],
)
def test_settings_and_lazy_exports_are_import_order_independent(source: str) -> None:
    completed = subprocess.run(
        [sys.executable, "-c", source],
        capture_output=True,
        text=True,
        timeout=10,
        check=False,
    )

    assert completed.returncode == 0, completed.stderr

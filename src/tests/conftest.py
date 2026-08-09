import pkgutil
from pathlib import Path

import pytest

import app.settings
from app.settings import (
    APIConfig,
    Config,
    FacebookConfig,
    JwtConfig,
    MediaStorageConfig,
    PostgresConfig,
    RedisConfig,
)

SHARED_DSN = "sqlite+aiosqlite:///file::memory:?cache=shared&uri=true"


def _test_database_url(self):
    return SHARED_DSN


Config.database_url = property(_test_database_url)

_test_config = Config(
    env="local",
    api=APIConfig(allowed_hosts=["*"]),
    facebook=FacebookConfig(data_dir=Path("storage/test-facebook")),
    jwt=JwtConfig(secret_key="test-secret-key-for-testing-only"),
    media=MediaStorageConfig(
        backend="local",
        signing_secret="test-media-signing-secret-at-least-32-characters",
    ),
    postgres=PostgresConfig(user="test", password="test", host="localhost", db="test"),
    redis=RedisConfig(host="localhost"),
)

app.settings.get_config = lambda: _test_config

_FIXTURES_ROOT = Path(__file__).parent / "fixtures"

# Collect all fixture modules
fixture_modules = []
for mod in pkgutil.walk_packages([_FIXTURES_ROOT.as_posix()], prefix="tests.fixtures."):
    if not mod.ispkg:
        fixture_modules.append(mod.name)

pytest_plugins = fixture_modules

_REFACTORED_TEST_ROOTS = {"accounts", "ad_library", "facebook", "observability"}
_TEST_KINDS = {"unit", "contract", "integration", "browser", "smoke"}


def pytest_collection_modifyitems(items: list[pytest.Item]) -> None:
    missing: list[str] = []
    for item in items:
        path = Path(str(item.path))
        try:
            relative = path.relative_to(Path(__file__).parent)
        except ValueError:
            continue
        if not relative.parts or relative.parts[0] not in _REFACTORED_TEST_ROOTS:
            continue
        if not any(item.get_closest_marker(name) for name in _TEST_KINDS):
            missing.append(item.nodeid)
    if missing:
        raise pytest.UsageError(
            "Refactored module tests require an explicit test-kind marker:\n"
            + "\n".join(missing)
        )

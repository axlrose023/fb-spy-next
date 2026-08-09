from __future__ import annotations

import pytest

from app.browser import ioc as browser_ioc
from app.ioc import get_async_container

pytestmark = pytest.mark.unit


def test_unavailable_browser_provider_is_omitted(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(browser_ioc, "_BROWSER_PROVIDER_ENABLED", False)

    assert browser_ioc.browser_provider_available() is False
    assert browser_ioc.browser_provider() is None


@pytest.mark.asyncio
async def test_root_container_builds_without_optional_browser_dependencies() -> None:
    container = get_async_container()
    await container.close()

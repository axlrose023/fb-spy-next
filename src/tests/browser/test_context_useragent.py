from __future__ import annotations

from typing import Any, cast

import pytest
from playwright.async_api import Browser, BrowserContext

pytest.importorskip("fake_useragent")

import app.browser.context as context_module
import app.browser.useragent as useragent_module
from app.browser import ContextFactory, UserAgentProvider
from app.browser.settings import UserAgentConfig, ViewportConfig

pytestmark = pytest.mark.unit


class StubUserAgentProvider:
    def get(self) -> str:
        return "test-user-agent"


class FakeBrowser:
    def __init__(self) -> None:
        self.options: dict[str, Any] | None = None
        self.context = object()

    async def new_context(self, **options: Any) -> BrowserContext:
        self.options = options
        return cast(BrowserContext, self.context)


@pytest.mark.asyncio
async def test_context_factory_uses_selected_agent_and_random_viewport(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    values = iter((1440, 900))
    monkeypatch.setattr(context_module.random, "randint", lambda *_: next(values))
    factory = ContextFactory(
        cast(UserAgentProvider, StubUserAgentProvider()),
        ViewportConfig(
            width_min=1280,
            width_max=1920,
            height_min=800,
            height_max=1080,
        ),
    )
    browser = FakeBrowser()

    context, metadata = await factory.create(cast(Browser, browser))

    expected_viewport = {"width": 1440, "height": 900}
    assert context is browser.context
    assert browser.options == {
        "viewport": expected_viewport,
        "user_agent": "test-user-agent",
    }
    assert metadata == {
        "user_agent": "test-user-agent",
        "viewport": expected_viewport,
    }


def test_user_agent_provider_falls_back_when_initialization_fails(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fail_to_initialize(**_: object) -> None:
        raise RuntimeError("unavailable")

    monkeypatch.setattr(useragent_module, "UserAgent", fail_to_initialize)
    provider = UserAgentProvider(UserAgentConfig(fallback="fallback-agent"))

    assert provider.get() == "fallback-agent"


def test_user_agent_provider_falls_back_when_random_lookup_fails(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class BrokenUserAgent:
        @property
        def random(self) -> str:
            raise RuntimeError("lookup failed")

    monkeypatch.setattr(
        useragent_module,
        "UserAgent",
        lambda **_: BrokenUserAgent(),
    )
    provider = UserAgentProvider(UserAgentConfig(fallback="fallback-agent"))

    assert provider.get() == "fallback-agent"

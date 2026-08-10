from __future__ import annotations

import subprocess
import sys
from typing import Any, cast

import pytest
from playwright.async_api import Browser, Playwright

import app.browser.pool as pool_module
from app.browser import BrowserPool
from app.browser.settings import PlaywrightConfig

pytestmark = pytest.mark.unit


class FakeBrowser:
    def __init__(self) -> None:
        self.closed = False

    async def close(self) -> None:
        self.closed = True


class FakeChromium:
    def __init__(self) -> None:
        self.browsers: list[FakeBrowser] = []
        self.launches: list[dict[str, Any]] = []

    async def launch(self, **options: Any) -> Browser:
        browser = FakeBrowser()
        self.browsers.append(browser)
        self.launches.append(options)
        return cast(Browser, browser)


class FakePlaywright:
    def __init__(self) -> None:
        self.chromium = FakeChromium()
        self.stopped = False

    async def stop(self) -> None:
        self.stopped = True


class FakePlaywrightStarter:
    def __init__(self, playwright: FakePlaywright) -> None:
        self.playwright = playwright

    async def start(self) -> Playwright:
        return cast(Playwright, self.playwright)


@pytest.mark.asyncio
async def test_pool_scales_slots_and_closes_removed_browsers(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    playwright = FakePlaywright()
    monkeypatch.setattr(
        pool_module,
        "async_playwright",
        lambda: FakePlaywrightStarter(playwright),
    )

    async def skip_delay(_: float) -> None:
        return None

    monkeypatch.setattr(pool_module.asyncio, "sleep", skip_delay)
    config = PlaywrightConfig(
        headless=False,
        max_browsers=2,
        contexts_per_browser=3,
        browser_args=["--test-browser-arg"],
    )
    pool = BrowserPool(config=config)

    await pool.start()

    assert pool.browser_count == 1
    assert pool.max_parallel == 6
    assert playwright.chromium.launches == [
        {"headless": False, "args": ["--test-browser-arg"]}
    ]
    first, first_slots = pool.get_browser(0)
    assert first is playwright.chromium.browsers[0]
    assert first_slots.qsize() == 3

    await pool.scale_for_tasks(4)

    assert pool.browser_count == 2
    second, second_slots = pool.get_browser(3)
    assert second is playwright.chromium.browsers[1]
    assert second_slots.qsize() == 3

    await pool.scale_down()

    assert pool.browser_count == 1
    assert playwright.chromium.browsers[1].closed is True

    await pool.stop()

    assert pool.browser_count == 0
    assert playwright.chromium.browsers[0].closed is True
    assert playwright.stopped is True


@pytest.mark.parametrize(
    "source",
    [
        "from app.settings import Config; from app.browser import BrowserPool",
        "from app.browser import BrowserPool; from app.settings import Config",
    ],
)
def test_settings_and_pool_are_import_order_independent(source: str) -> None:
    completed = subprocess.run(
        [sys.executable, "-c", source],
        capture_output=True,
        text=True,
        timeout=10,
        check=False,
    )

    assert completed.returncode == 0, completed.stderr

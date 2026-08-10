from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from app.facebook.collection import CollectedAd
from app.facebook.enrichment.landing.adapters.playwright import (
    SCROLL_CTA_JS,
    artifacts,
    capture,
    neutralize_profile_pages,
    resolve_in_view,
)

pytestmark = pytest.mark.unit


class FakeKeyboard:
    def __init__(self) -> None:
        self.pressed: list[str] = []

    def press(self, key: str) -> None:
        self.pressed.append(key)


class FakeLocator:
    def __init__(self, on_click: Any = None) -> None:
        self.on_click = on_click
        self.clicks: list[dict[str, Any]] = []

    @property
    def first(self) -> FakeLocator:
        return self

    def click(self, **kwargs: Any) -> None:
        self.clicks.append(kwargs)
        if self.on_click:
            self.on_click()


class FakePage:
    def __init__(
        self,
        url: str,
        *,
        cta_results: list[dict[str, Any] | None] | None = None,
    ) -> None:
        self.url = url
        self.cta_results = list(cta_results or [])
        self.keyboard = FakeKeyboard()
        self.locator_result = FakeLocator()
        self.closed = False
        self.context: FakeContext | None = None
        self.goto_calls: list[tuple[str, dict[str, Any]]] = []
        self.evaluations: list[tuple[str, Any]] = []

    def evaluate(self, script: str, payload: Any = None) -> Any:
        self.evaluations.append((script, payload))
        if script == SCROLL_CTA_JS:
            return self.cta_results.pop(0) if self.cta_results else None
        return None

    def locator(self, selector: str) -> FakeLocator:
        assert selector == '[data-fbspy-cta="1"]'
        return self.locator_result

    def wait_for_load_state(self, _state: str, *, timeout: int) -> None:
        assert timeout == 12000

    def is_closed(self) -> bool:
        return self.closed

    def close(self, **_kwargs: Any) -> None:
        self.closed = True
        if self.context and self in self.context.pages:
            self.context.pages.remove(self)

    def goto(self, url: str, **kwargs: Any) -> None:
        self.goto_calls.append((url, kwargs))
        self.url = url


class ExpectedPage:
    def __init__(
        self,
        context: FakeContext,
        landing: FakePage,
        *,
        fail_on_exit: bool,
    ) -> None:
        self.context = context
        self.value = landing
        self.fail_on_exit = fail_on_exit

    def __enter__(self) -> ExpectedPage:
        if not self.fail_on_exit:
            self.value.context = self.context
            self.context.pages.append(self.value)
        return self

    def __exit__(self, *_args: Any) -> None:
        if self.fail_on_exit:
            raise RuntimeError("page event timeout")


class FakeContext:
    def __init__(
        self,
        feed: FakePage,
        landing: FakePage | None = None,
        *,
        fail_on_exit: bool = False,
    ) -> None:
        self.pages = [feed]
        self.feed = feed
        self.landing = landing or FakePage("about:blank")
        self.fail_on_exit = fail_on_exit
        feed.context = self

    def expect_page(self, *, timeout: int) -> ExpectedPage:
        assert timeout == 8000
        return ExpectedPage(
            self,
            self.landing,
            fail_on_exit=self.fail_on_exit,
        )


class FakeDebugRecorder:
    def __init__(self) -> None:
        self.events: list[tuple[str, dict[str, Any]]] = []
        self.screenshots: list[tuple[FakePage, str]] = []

    def event(self, kind: str, **payload: Any) -> None:
        self.events.append((kind, payload))

    def screenshot(
        self,
        page: FakePage,
        relative: str,
        *,
        full_page: bool = False,
    ) -> None:
        assert full_page is False
        self.screenshots.append((page, relative))


def _patch_artifacts(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        artifacts,
        "wait_for_landing_page_ready",
        lambda *_args, **_kwargs: None,
    )
    monkeypatch.setattr(
        artifacts,
        "save_landing_screenshot_from_browser",
        lambda *_args, **_kwargs: "landing_screens/loaded.png",
    )
    monkeypatch.setattr(
        artifacts,
        "archive_landing_page_from_browser",
        lambda *_args, **_kwargs: "landing_archives/page.zip",
    )


def test_new_tab_landing_is_captured_archived_and_closed(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    feed = FakePage(
        "https://m.facebook.com/",
        cta_results=[{"kind": "detected_target"}, {"kind": "detected_target"}],
    )
    landing = FakePage(
        "https://offer.example/path?utm_source=facebook&ad_id=123456789012"
    )
    context = FakeContext(feed, landing)
    debug = FakeDebugRecorder()
    ad = CollectedAd(
        advertiser="Relevant advertiser",
        ad_type="link",
        displayed_domain="offer.example",
    )
    delays: list[float] = []
    recoveries: list[str] = []
    monkeypatch.setattr(capture.time, "sleep", delays.append)
    monkeypatch.setattr(
        capture,
        "recover_facebook_feed",
        lambda _page, *, feed_url: recoveries.append(feed_url),
    )
    _patch_artifacts(monkeypatch)

    resolve_in_view(
        feed,
        context,
        ad,
        None,
        "feed-element",
        tmp_path,
        debug=debug,
        debug_id=7,
    )

    assert delays == [0.8, 1.0]
    assert feed.locator_result.clicks == [{"timeout": 1500, "no_wait_after": True}]
    assert ad.landing_full == landing.url
    assert ad.landing_clean == "https://offer.example/path"
    assert ad.fb_ad_id == "123456789012"
    assert ad.landing_screenshot == "landing_screens/loaded.png"
    assert ad.landing_archive == "landing_archives/page.zip"
    assert landing.closed is True
    assert feed.keyboard.pressed == ["Escape"]
    assert recoveries == ["https://m.facebook.com/"]
    assert [kind for kind, _payload in debug.events] == [
        "resolve_start",
        "resolve_new_page",
        "landing_screenshot_saved",
        "landing_archived",
        "resolve_finish",
    ]


def test_same_tab_navigation_is_recovered_after_page_event_timeout(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    feed = FakePage(
        "https://m.facebook.com/",
        cta_results=[{"kind": "link_card"}, {"kind": "link_card"}],
    )
    context = FakeContext(feed, fail_on_exit=True)
    feed.locator_result.on_click = lambda: setattr(
        feed,
        "url",
        "https://offer.example/same-tab?sub5=987654321012",
    )
    ad = CollectedAd(advertiser="Relevant", ad_type="link")
    debug = FakeDebugRecorder()
    monkeypatch.setattr(capture.time, "sleep", lambda _seconds: None)
    monkeypatch.setattr(capture, "recover_facebook_feed", lambda *_a, **_k: None)
    _patch_artifacts(monkeypatch)

    resolve_in_view(
        feed,
        context,
        ad,
        None,
        "feed-element",
        tmp_path,
        debug=debug,
        archive_landing=False,
    )

    assert ad.landing_full == feed.url
    assert ad.landing_clean == "https://offer.example/same-tab"
    assert ad.fb_ad_id == "987654321012"
    assert ad.landing_screenshot == "landing_screens/loaded.png"
    assert ad.landing_archive is None
    assert "resolve_click_timeout_recovered" in [
        kind for kind, _payload in debug.events
    ]


def test_missing_cta_closes_stale_tabs_without_profile_navigation(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    feed = FakePage("https://m.facebook.com/", cta_results=[None])
    context = FakeContext(feed)
    stale = FakePage("https://stale.example/")
    stale.context = context
    context.pages.append(stale)
    ad = CollectedAd(advertiser="Relevant", ad_type="link")
    recoveries: list[bool] = []
    monkeypatch.setattr(
        capture,
        "recover_facebook_feed",
        lambda *_a, **_k: recoveries.append(True),
    )

    resolve_in_view(feed, context, ad, None, "feed-element", tmp_path)

    assert stale.closed is True
    assert ad.landing_full is None
    assert feed.keyboard.pressed == []
    assert recoveries == []


def test_profile_neutralization_preserves_feed_page_and_devtools() -> None:
    feed = FakePage("https://m.facebook.com/")
    context = FakeContext(feed)
    stale = FakePage("https://offer.example/")
    devtools = FakePage("devtools://devtools/bundled/inspector.html")
    for page in (stale, devtools):
        page.context = context
        context.pages.append(page)

    neutralize_profile_pages(feed, context)

    assert stale.closed is True
    assert devtools.closed is False
    assert feed.goto_calls == [
        ("about:blank", {"wait_until": "commit", "timeout": 5000})
    ]

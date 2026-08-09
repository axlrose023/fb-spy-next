from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
from PIL import Image

from app.facebook.collection.adapters.playwright import (
    MEDIA_READY_JS,
    VIDEO_CREATIVE_JS,
    has_video_creative,
    save_ad_screenshot,
    screenshot_has_blank_media,
)
from app.facebook.collection.adapters.playwright import screenshot as screenshot_module
from app.services import facebook_runner

pytestmark = pytest.mark.unit


class FakeLocator:
    def __init__(self) -> None:
        self.scrolls: list[int] = []
        self.screenshots: list[dict[str, Any]] = []

    @property
    def first(self) -> FakeLocator:
        return self

    def scroll_into_view_if_needed(self, *, timeout: int) -> None:
        self.scrolls.append(timeout)

    def bounding_box(self, *, timeout: int) -> dict[str, int]:
        assert timeout == 5000
        return {"width": 500, "height": 700}

    def screenshot(self, **kwargs: Any) -> None:
        self.screenshots.append(kwargs)


class FakePage:
    def __init__(self, *, video: bool = False) -> None:
        self.locator_result = FakeLocator()
        self.waits: list[dict[str, Any]] = []
        self.viewport_screenshots: list[dict[str, Any]] = []
        self.video = video

    def locator(self, selector: str) -> FakeLocator:
        assert selector == '[data-fbspy-id="feed-element"]'
        return self.locator_result

    def wait_for_function(self, script: str, **kwargs: Any) -> None:
        assert script == MEDIA_READY_JS
        self.waits.append(kwargs)

    def screenshot(self, **kwargs: Any) -> None:
        self.viewport_screenshots.append(kwargs)

    def evaluate(self, script: str, element_id: str) -> bool:
        assert script == VIDEO_CREATIVE_JS
        assert element_id == "feed-element"
        return self.video


def test_blank_media_qa_distinguishes_placeholder_from_creative(
    tmp_path: Path,
) -> None:
    blank = tmp_path / "blank.png"
    creative = tmp_path / "creative.png"
    Image.new("RGB", (400, 800), "white").save(blank)
    Image.new("RGB", (400, 800), "red").save(creative)

    assert screenshot_has_blank_media(blank) is True
    assert screenshot_has_blank_media(creative) is False
    assert screenshot_has_blank_media(tmp_path / "missing.png") is False


def test_media_screenshot_retries_once_after_blank_capture(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    page = FakePage()
    checks = iter((True, False))
    delays: list[float] = []
    monkeypatch.setattr(
        screenshot_module,
        "screenshot_has_blank_media",
        lambda _path: next(checks),
    )
    monkeypatch.setattr(screenshot_module.time, "sleep", delays.append)

    exact = save_ad_screenshot(
        page,
        tmp_path / "ad.png",
        "feed-element",
        expect_media=True,
    )

    assert exact is True
    assert page.locator_result.scrolls == [5000, 5000]
    assert page.waits == [
        {"arg": "feed-element", "timeout": 3000},
        {"arg": "feed-element", "timeout": 5000},
    ]
    assert delays == [0.5, 1.5]
    assert len(page.locator_result.screenshots) == 2
    assert page.viewport_screenshots == []


def test_interest_safe_screenshot_pauses_media_and_uses_short_wait(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    page = FakePage()
    pauses: list[FakePage] = []
    delays: list[float] = []
    monkeypatch.setattr(
        screenshot_module,
        "pause_all_videos",
        lambda target: pauses.append(target),
    )
    monkeypatch.setattr(
        screenshot_module,
        "screenshot_has_blank_media",
        lambda _path: False,
    )
    monkeypatch.setattr(screenshot_module.time, "sleep", delays.append)

    exact = save_ad_screenshot(
        page,
        tmp_path / "safe.png",
        "feed-element",
        expect_media=True,
        interest_safe=True,
    )

    assert exact is True
    assert pauses == [page]
    assert page.waits == [{"arg": "feed-element", "timeout": 1200}]
    assert delays == [0.15]
    assert len(page.locator_result.screenshots) == 1


def test_missing_element_uses_viewport_fallback() -> None:
    page = FakePage()

    exact = save_ad_screenshot(page, Path("fallback.png"), None)

    assert exact is False
    assert page.viewport_screenshots == [{"path": "fallback.png"}]


def test_video_creative_probe_is_best_effort() -> None:
    assert has_video_creative(FakePage(video=True), "feed-element") is True
    assert has_video_creative(FakePage(video=False), "feed-element") is False
    assert has_video_creative(FakePage(video=True), None) is False


def test_runner_screenshot_aliases_share_canonical_implementation() -> None:
    assert facebook_runner.MEDIA_READY_JS is MEDIA_READY_JS
    assert facebook_runner.VIDEO_CREATIVE_JS is VIDEO_CREATIVE_JS
    assert facebook_runner._screenshot_has_blank_media is screenshot_has_blank_media
    assert facebook_runner.save_ad_screenshot is save_ad_screenshot
    assert facebook_runner.has_video_creative is has_video_creative

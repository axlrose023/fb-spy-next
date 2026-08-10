from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from app.facebook.collection.adapters.playwright import collect_feed
from app.facebook.collection.adapters.playwright.feed_reader import SCROLL_JS
from app.facebook.feed import DETECT_JS
from app.facebook.navigation.adapters.playwright import FACEBOOK_LOGIN_PROBE_JS

pytestmark = pytest.mark.unit


class FeedPage:
    def __init__(self, rows: list[dict[str, Any]]) -> None:
        self.rows = rows
        self.url = "https://m.facebook.com/"
        self.scrolls: list[int] = []

    def goto(self, url: str, **_kwargs: object) -> None:
        self.url = url

    def evaluate(self, script: str, value: Any = None) -> Any:
        if script == FACEBOOK_LOGIN_PROBE_JS:
            return False
        if script == DETECT_JS:
            return list(self.rows)
        if script == SCROLL_JS:
            self.scrolls.append(int(value))
            return None
        raise AssertionError("unexpected JavaScript")


def test_empty_authenticated_feed_ends_at_scroll_budget(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    page = FeedPage([])
    monkeypatch.setattr("time.sleep", lambda _seconds: None)

    ads = collect_feed(
        page,
        object(),
        tmp_path,
        minutes=15,
        max_scrolls=1,
        shots=False,
        do_resolve=False,
        resolve_max=0,
        scroll_px=520,
    )

    summary = json.loads((tmp_path / "summary.json").read_text(encoding="utf-8"))
    assert ads == {}
    assert summary["stop_reason"] == "scroll_budget"
    assert summary["facebook_login_required"] is False
    assert summary["scrolls"] == 1
    assert len(page.scrolls) == 1


def test_explicit_stop_callback_prevents_candidate_processing(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    page = FeedPage([{"advertiser": "Must not be accepted"}])
    monkeypatch.setattr("time.sleep", lambda _seconds: None)

    ads = collect_feed(
        page,
        object(),
        tmp_path,
        minutes=15,
        max_scrolls=10,
        shots=False,
        do_resolve=False,
        resolve_max=0,
        scroll_px=520,
        stop_requested=lambda: True,
    )

    summary = json.loads((tmp_path / "summary.json").read_text(encoding="utf-8"))
    assert ads == {}
    assert summary["stop_reason"] == "interrupted"
    assert summary["captured_candidates"] == 0
    assert summary["scrolls"] == 0

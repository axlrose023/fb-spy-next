from __future__ import annotations

from typing import Any

import pytest

from app.facebook.collection.adapters.playwright import (
    DETECT_JS,
    SCROLL_JS,
    FeedReader,
)

pytestmark = pytest.mark.unit


class Locator:
    first: Locator

    def __init__(self) -> None:
        self.first = self

    def evaluate(self, script: str, *, timeout: int) -> str:
        assert script == "el => el.outerHTML"
        assert timeout == 5000
        return "<article>ad</article>"


class Page:
    def __init__(self) -> None:
        self.calls: list[tuple[str, Any]] = []
        self.locator_query = ""

    def evaluate(self, script: str, payload: Any = None) -> Any:
        self.calls.append((script, payload))
        if script == DETECT_JS:
            return [{"advertiser": "Publisher"}]
        return None

    def locator(self, query: str) -> Locator:
        self.locator_query = query
        return Locator()


def test_passive_reader_pauses_media_before_detection() -> None:
    page = Page()

    rows = FeedReader(page, passive=True).detect()

    assert rows == [{"advertiser": "Publisher"}]
    assert len(page.calls) == 2
    assert "__fbSpyPassiveMediaGuard" in page.calls[0][0]
    assert page.calls[1] == (DETECT_JS, None)


def test_reader_owns_card_dom_and_scroll_browser_operations() -> None:
    page = Page()
    reader = FeedReader(page)

    assert reader.card_html("candidate-1") == "<article>ad</article>"
    reader.scroll(520)

    assert page.locator_query == '[data-fbspy-id="candidate-1"]'
    assert page.calls[-1] == (SCROLL_JS, 520)

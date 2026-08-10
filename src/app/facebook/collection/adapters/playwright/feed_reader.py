from __future__ import annotations

from dataclasses import dataclass
from typing import Any, cast

from app.facebook.feed import DETECT_JS, pause_all_videos

SCROLL_JS = 'dy => window.scrollBy({top: dy, left: 0, behavior: "smooth"})'


@dataclass(slots=True)
class FeedReader:
    page: Any
    passive: bool = False

    def detect(self) -> list[dict[str, Any]]:
        if self.passive:
            pause_all_videos(self.page)
        return cast(list[dict[str, Any]], self.page.evaluate(DETECT_JS))

    def card_html(self, element_id: str) -> str:
        locator = self.page.locator(f'[data-fbspy-id="{element_id}"]').first
        return cast(str, locator.evaluate("el => el.outerHTML", timeout=5000))

    def scroll(self, pixels: int) -> None:
        self.page.evaluate(SCROLL_JS, pixels)

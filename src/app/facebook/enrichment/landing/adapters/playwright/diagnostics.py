from __future__ import annotations

from typing import Any, Protocol


class DebugRecorderPort(Protocol):
    def event(self, kind: str, **payload: Any) -> None: ...

    def screenshot(
        self,
        page: Any,
        relative: str,
        *,
        full_page: bool = False,
    ) -> None: ...


def page_url(page: Any) -> str:
    try:
        url: str = page.url
        return url
    except Exception:
        return ""

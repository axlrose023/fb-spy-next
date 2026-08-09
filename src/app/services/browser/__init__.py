"""Compatibility facade for browser infrastructure."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from app.browser import BrowserPool, ContextFactory, UserAgentProvider

__all__ = ["BrowserPool", "ContextFactory", "UserAgentProvider"]


def __getattr__(name: str) -> Any:
    if name not in __all__:
        raise AttributeError(name)
    import app.browser as browser

    value = getattr(browser, name)
    globals()[name] = value
    return value

from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from .ioc import browser_provider, browser_provider_available

__all__ = ["browser_provider", "browser_provider_available"]


def __getattr__(name: str) -> Any:
    if name not in __all__:
        raise AttributeError(name)
    from . import ioc

    value = getattr(ioc, name)
    globals()[name] = value
    return value

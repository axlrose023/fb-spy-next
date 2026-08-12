"""Advertisement library application."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from .ads.adapters.persistence import FacebookAd as FacebookAdRecord
    from .media.configuration import configured_storage

__all__ = ["FacebookAdRecord", "configured_storage"]


def __getattr__(name: str) -> Any:
    value: Any
    if name == "configured_storage":
        from .media.configuration import configured_storage

        value = configured_storage
    elif name == "FacebookAdRecord":
        from .ads.adapters.persistence import FacebookAd

        value = FacebookAd
    else:
        raise AttributeError(name)
    globals()[name] = value
    return value

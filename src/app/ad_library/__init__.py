"""Advertisement library application."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from .media.configuration import configured_storage

__all__ = ["configured_storage"]


def __getattr__(name: str) -> Any:
    if name != "configured_storage":
        raise AttributeError(name)
    from .media.configuration import configured_storage

    globals()[name] = configured_storage
    return configured_storage

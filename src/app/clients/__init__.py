"""HTTP clients for external services integration."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from app.clients.base import HttpClient, HttpClientError
    from app.clients.providers import HttpClientsProvider

__all__ = ["HttpClient", "HttpClientError", "HttpClientsProvider"]


def __getattr__(name: str) -> Any:
    if name == "HttpClientsProvider":
        from app.clients.providers import HttpClientsProvider

        value = HttpClientsProvider
    elif name in {"HttpClient", "HttpClientError"}:
        from app.clients import base

        value = getattr(base, name)
    else:
        raise AttributeError(name)
    globals()[name] = value
    return value

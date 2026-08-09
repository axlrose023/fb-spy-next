from __future__ import annotations

from collections.abc import Callable
from typing import Any

OctoGetCallback = Callable[[str], dict[str, Any] | list[Any]]
OctoPostCallback = Callable[
    [str, dict[str, Any]],
    dict[str, Any] | list[Any],
]


class CallbackOctoTransport:
    """Adapt legacy Octo request callbacks to the canonical transport port."""

    def __init__(
        self,
        get: OctoGetCallback,
        post: OctoPostCallback,
    ) -> None:
        self._get = get
        self._post = post

    def request(
        self,
        method: str,
        path: str,
        body: dict[str, Any] | None = None,
        *,
        timeout_seconds: float | None = None,
    ) -> dict[str, Any] | list[Any]:
        del timeout_seconds
        if method == "GET":
            return self._get(path)
        return self._post(path, body or {})

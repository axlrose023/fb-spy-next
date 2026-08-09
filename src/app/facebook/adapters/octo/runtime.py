from __future__ import annotations

import time
from collections.abc import Callable, Iterable
from typing import Any, cast

from app.facebook.profiles import ActiveProfile, ProfileSession, ProfileSourceError

from .client import OctoHttpClient
from .sessions import OctoProfileSessionManager, OctoTransport

DEFAULT_OCTO_START_FLAGS = (
    "--no-sandbox",
    "--disable-gpu",
    "--disable-dev-shm-usage",
    "--remote-debugging-address=0.0.0.0",
)


class OctoApiError(RuntimeError):
    pass


class OctoLocalRuntime:
    def __init__(
        self,
        api_url: str,
        profile_uuid: str,
        *,
        headless: bool = False,
        start_flags: Iterable[str] = DEFAULT_OCTO_START_FLAGS,
        client: OctoTransport | None = None,
        sleeper: Callable[[float], None] = time.sleep,
    ) -> None:
        self._profile_uuid = profile_uuid
        self._headless = headless
        self._client = client if client is not None else OctoHttpClient(api_url)
        self._sessions = OctoProfileSessionManager(
            self,
            start_flags=list(start_flags),
            sleeper=sleeper,
        )

    def request(
        self,
        method: str,
        path: str,
        body: dict[str, Any] | None = None,
        *,
        timeout_seconds: float | None = None,
    ) -> dict[str, Any] | list[Any]:
        try:
            return cast(
                dict[str, Any] | list[Any],
                self._client.request(
                    method,
                    path,
                    body,
                    timeout_seconds=timeout_seconds,
                ),
            )
        except ProfileSourceError as exc:
            raise OctoApiError(str(exc)) from exc

    def active(self) -> list[ActiveProfile]:
        return cast(list[ActiveProfile], self._sessions.active())

    def start(
        self,
        profile_uuid: str | None = None,
        *,
        headless: bool | None = None,
    ) -> ProfileSession:
        return self._sessions.start(
            profile_uuid or self._profile_uuid,
            headless=self._headless if headless is None else headless,
        )

    def stop(self, profile_uuid: str | None = None) -> None:
        self._sessions.stop(profile_uuid or self._profile_uuid)

    def acquire(
        self,
        profile_uuid: str | None = None,
        *,
        headless: bool | None = None,
    ) -> ProfileSession:
        return self._sessions.acquire(
            profile_uuid or self._profile_uuid,
            headless=self._headless if headless is None else headless,
        )

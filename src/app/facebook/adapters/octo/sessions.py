from __future__ import annotations

import time
from collections.abc import Callable
from typing import Any, Protocol

from app.facebook.profiles import (
    ActiveProfile,
    ProfileSession,
    ProfileSessionError,
)

from .mapping import active_profile_from_raw, session_from_raw


class OctoTransport(Protocol):
    def request(
        self,
        method: str,
        path: str,
        body: dict[str, Any] | None = None,
        *,
        timeout_seconds: float | None = None,
    ) -> dict[str, Any] | list[Any]: ...


class OctoProfileSessionManager:
    def __init__(
        self,
        client: OctoTransport,
        *,
        start_flags: list[str] | None = None,
        sleeper: Callable[[float], None] = time.sleep,
    ) -> None:
        self._client = client
        self._start_flags = list(start_flags or [])
        self._sleep = sleeper

    def active(self) -> list[ActiveProfile]:
        payload = self._client.request("GET", "/api/profiles/active")
        if not isinstance(payload, list):
            return []
        profiles = [
            mapped
            for raw in payload
            if isinstance(raw, dict)
            and (mapped := active_profile_from_raw(raw)) is not None
        ]
        return profiles

    def start(self, profile_uuid: str, *, headless: bool) -> ProfileSession:
        payload = self._client.request(
            "POST",
            "/api/profiles/start",
            {
                "uuid": profile_uuid,
                "headless": headless,
                "debug_port": True,
                "flags": self._start_flags,
                "timeout": 120,
            },
            timeout_seconds=150,
        )
        if not isinstance(payload, dict):
            raise ProfileSessionError("Octo profile start returned an invalid payload")
        self._sleep(2)
        return session_from_raw(payload)

    def stop(self, profile_uuid: str) -> None:
        self._client.request(
            "POST",
            "/api/profiles/stop",
            {"uuid": profile_uuid},
        )

    def acquire(self, profile_uuid: str, *, headless: bool) -> ProfileSession:
        current = next(
            (
                profile
                for profile in self.active()
                if profile.octo_profile_uuid == profile_uuid
            ),
            None,
        )
        if current is None:
            return self.start(profile_uuid, headless=headless)
        if current.headless != headless or current.ws_endpoint is None:
            self.stop(profile_uuid)
            self._sleep(3)
            return self.start(profile_uuid, headless=headless)
        return ProfileSession(current.ws_endpoint, current.connection)

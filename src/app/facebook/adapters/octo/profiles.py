from __future__ import annotations

import urllib.parse
from typing import Any

from app.facebook.profiles import DiscoveredProfile

from .mapping import active_discovery_profile, public_profile_from_raw
from .sessions import OctoProfileSessionManager, OctoTransport


class OctoPublicProfileSource:
    def __init__(self, client: OctoTransport, *, page_size: int = 100) -> None:
        self._client = client
        self._page_size = page_size

    def discover(self, *, search_tags: str = "") -> list[DiscoveredProfile]:
        page = 0
        profiles: list[DiscoveredProfile] = []
        seen: set[str] = set()
        while True:
            payload = self._client.request(
                "GET",
                self._path(page=page, search_tags=search_tags),
            )
            data = payload.get("data", []) if isinstance(payload, dict) else []
            if not isinstance(data, list) or not data:
                break
            for raw in data:
                mapped = public_profile_from_raw(raw) if isinstance(raw, dict) else None
                if mapped is None or mapped.octo_profile_uuid in seen:
                    continue
                seen.add(mapped.octo_profile_uuid)
                profiles.append(mapped)
            total_count = _int_or_default(
                payload.get("total_count") if isinstance(payload, dict) else None,
                len(profiles),
            )
            if len(profiles) >= total_count:
                break
            page += 1
        return profiles

    def _path(self, *, page: int, search_tags: str) -> str:
        query: dict[str, str | int] = {
            "page_len": self._page_size,
            "page": page,
            "fields": ("title,description,proxy,tags,status,last_active,extra_info"),
            "ordering": "active",
        }
        if search_tags:
            query["search_tags"] = search_tags
        return "/api/v2/automation/profiles?" + urllib.parse.urlencode(query)


class OctoActiveProfileSource:
    def __init__(self, sessions: OctoProfileSessionManager) -> None:
        self._sessions = sessions

    def discover(self, *, search_tags: str = "") -> list[DiscoveredProfile]:
        del search_tags
        return [
            active_discovery_profile(profile) for profile in self._sessions.active()
        ]


def _int_or_default(value: Any, default: int) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default

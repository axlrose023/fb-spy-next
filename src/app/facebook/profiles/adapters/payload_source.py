from __future__ import annotations

from collections.abc import Callable
from typing import Any

from ..models import DiscoveredProfile

ProfilePayloadLoader = Callable[[str], list[dict[str, Any]]]


class OctoPayloadProfileSource:
    """Map the legacy Octo profile payload without trusting proxy geo metadata."""

    def __init__(self, load: ProfilePayloadLoader) -> None:
        self._load = load

    def discover(self, *, search_tags: str = "") -> list[DiscoveredProfile]:
        return [
            DiscoveredProfile(
                octo_profile_uuid=str(raw["uuid"]),
                label=str(raw.get("title") or str(raw["uuid"])[:8]),
            )
            for raw in self._load(search_tags)
            if raw.get("uuid")
        ]

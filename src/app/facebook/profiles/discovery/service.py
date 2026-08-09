from __future__ import annotations

from ..contracts import ProfileCatalog, ProfileDiscoverySource
from ..models import DiscoveryResult


class ProfileDiscoveryService:
    def __init__(
        self,
        catalog: ProfileCatalog,
        source: ProfileDiscoverySource,
    ) -> None:
        self._catalog = catalog
        self._source = source

    def discover(
        self,
        *,
        search_tags: str = "",
        enable_new: bool = False,
    ) -> DiscoveryResult:
        candidates = self._source.discover(search_tags=search_tags)
        profiles = [
            candidate.configured(enabled=enable_new) for candidate in candidates
        ]
        return DiscoveryResult(
            discovered=len(candidates),
            added=self._catalog.add_missing(profiles),
        )

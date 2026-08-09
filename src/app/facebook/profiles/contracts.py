from __future__ import annotations

from typing import Protocol

from .models import ActiveProfile, DiscoveredProfile, Profile, ProfileSession


class ProfileCatalog(Protocol):
    def list_profiles(self) -> list[Profile]: ...

    def add_missing(self, profiles: list[Profile]) -> int: ...

    def adopt_country(self, profile_uuid: str, country: str) -> bool: ...


class ProfileDiscoverySource(Protocol):
    def discover(self, *, search_tags: str = "") -> list[DiscoveredProfile]: ...


class ProfileSessions(Protocol):
    def active(self) -> list[ActiveProfile]: ...

    def start(self, profile_uuid: str, *, headless: bool) -> ProfileSession: ...

    def stop(self, profile_uuid: str) -> None: ...

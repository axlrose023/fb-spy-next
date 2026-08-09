from __future__ import annotations

from .contracts import ProfileCatalog
from .discovery.geo import normalize_country
from .models import Profile


class ProfileService:
    def __init__(self, catalog: ProfileCatalog) -> None:
        self._catalog = catalog

    def list_profiles(self) -> list[Profile]:
        return self._catalog.list_profiles()

    def adopt_country(self, profile_uuid: str, country: str | None) -> bool:
        normalized = normalize_country(country)
        if normalized is None:
            return False
        return self._catalog.adopt_country(profile_uuid, normalized)

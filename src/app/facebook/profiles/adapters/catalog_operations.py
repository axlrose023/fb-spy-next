from __future__ import annotations

from pathlib import Path

from ..contracts import ProfileDiscoverySource
from ..discovery import ProfileDiscoveryService
from ..models import DiscoveryResult, Profile
from ..service import ProfileService
from .json_catalog import JsonProfileCatalog


def discover_catalog_profiles(
    path: Path,
    source: ProfileDiscoverySource,
    *,
    search_tags: str = "",
    enable_new: bool = False,
) -> DiscoveryResult:
    return ProfileDiscoveryService(JsonProfileCatalog(path), source).discover(
        search_tags=search_tags,
        enable_new=enable_new,
    )


def list_catalog_profiles(path: Path) -> list[Profile]:
    profiles: list[Profile] = JsonProfileCatalog(path).list_profiles()
    return profiles


def adopt_catalog_country(path: Path, profile_uuid: str, country: str) -> None:
    ProfileService(JsonProfileCatalog(path)).adopt_country(profile_uuid, country)

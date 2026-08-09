from __future__ import annotations

import json
from pathlib import Path

import pytest

from app.facebook.profiles import (
    DiscoveredProfile,
    ProfileDiscoveryService,
    ProfileService,
)
from app.facebook.profiles.adapters import JsonProfileCatalog

pytestmark = pytest.mark.unit


class StaticProfileSource:
    def __init__(self, profiles: list[DiscoveredProfile]) -> None:
        self._profiles = profiles
        self.search_tags: list[str] = []

    def discover(self, *, search_tags: str = "") -> list[DiscoveredProfile]:
        self.search_tags.append(search_tags)
        return list(self._profiles)


def test_discovery_adds_each_profile_once_and_keeps_public_geo_unknown(
    tmp_path: Path,
) -> None:
    catalog = JsonProfileCatalog(tmp_path / "profiles.json")
    source = StaticProfileSource(
        [
            DiscoveredProfile("profile-a", "A"),
            DiscoveredProfile("profile-a", "A duplicate"),
            DiscoveredProfile("profile-b", "B"),
        ]
    )
    discovery = ProfileDiscoveryService(catalog, source)

    first = discovery.discover(search_tags="facebook", enable_new=True)
    second = discovery.discover(search_tags="facebook", enable_new=True)

    assert (first.discovered, first.added) == (3, 2)
    assert (second.discovered, second.added) == (3, 0)
    assert source.search_tags == ["facebook", "facebook"]
    profiles = catalog.list_profiles()
    assert [profile.octo_profile_uuid for profile in profiles] == [
        "profile-a",
        "profile-b",
    ]
    assert all(profile.enabled for profile in profiles)
    assert all(profile.expected_country is None for profile in profiles)


def test_profile_service_normalizes_and_adopts_geo_only_once(tmp_path: Path) -> None:
    path = tmp_path / "profiles.json"
    path.write_text(
        json.dumps(
            {
                "profiles": [
                    {
                        "octo_profile_uuid": "turkey",
                        "failed_recovery_calibration_passes": 0,
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    service = ProfileService(JsonProfileCatalog(path))

    assert service.adopt_country("turkey", " tr ") is True
    assert service.adopt_country("turkey", "Spain") is False
    assert service.adopt_country("turkey", " ") is False
    assert service.adopt_country("missing", "Canada") is False

    [profile] = service.list_profiles()
    assert profile.expected_country == "Turkey"
    assert profile.failed_recovery_calibration_passes == 1


def test_corrupt_or_legacy_profile_payload_is_loaded_safely(tmp_path: Path) -> None:
    path = tmp_path / "profiles.json"
    path.write_text("not-json", encoding="utf-8")
    catalog = JsonProfileCatalog(path)

    assert catalog.list_profiles() == []

    path.write_text(
        json.dumps(
            [
                None,
                {"label": "missing id"},
                {"octo_profile_uuid": "valid", "enabled": False},
            ]
        ),
        encoding="utf-8",
    )
    [profile] = catalog.list_profiles()
    assert profile.octo_profile_uuid == "valid"
    assert profile.enabled is False

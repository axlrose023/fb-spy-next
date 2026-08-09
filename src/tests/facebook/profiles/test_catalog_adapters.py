from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from app.facebook.profiles.adapters import (
    OctoPayloadProfileSource,
    adopt_catalog_country,
    discover_catalog_profiles,
    list_catalog_profiles,
)

pytestmark = pytest.mark.unit


def test_payload_source_maps_safe_profile_fields_and_forwards_tags() -> None:
    requested_tags: list[str] = []

    def load(tags: str) -> list[dict[str, Any]]:
        requested_tags.append(tags)
        return [
            {
                "uuid": "profile-one",
                "title": "Profile One",
                "proxy": {"country": "TR", "password": "secret"},
            },
            {"uuid": "123456789-profile"},
            {"title": "missing uuid"},
        ]

    source = OctoPayloadProfileSource(load)

    profiles = source.discover(search_tags="facebook")

    assert requested_tags == ["facebook"]
    assert [
        (profile.octo_profile_uuid, profile.label, profile.observed_country)
        for profile in profiles
    ] == [
        ("profile-one", "Profile One", None),
        ("123456789-profile", "12345678", None),
    ]
    assert "secret" not in repr(profiles)


def test_catalog_operations_preserve_discovery_and_geo_rules(tmp_path: Path) -> None:
    path = tmp_path / "profiles.json"
    source = OctoPayloadProfileSource(
        lambda _tags: [
            {"uuid": "profile-one", "title": "Profile One"},
            {"uuid": "profile-one", "title": "Duplicate"},
        ]
    )

    first = discover_catalog_profiles(path, source, enable_new=True)
    second = discover_catalog_profiles(path, source, enable_new=False)
    adopt_catalog_country(path, "profile-one", " tr ")
    adopt_catalog_country(path, "profile-one", "Spain")

    assert (first.discovered, first.added) == (2, 1)
    assert (second.discovered, second.added) == (2, 0)
    [profile] = list_catalog_profiles(path)
    assert profile.enabled is True
    assert profile.expected_country == "Turkey"

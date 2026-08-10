from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from app.facebook.calibration import CalibrationPolicy, baseline_from_history
from app.facebook.profiles import normalize_country
from app.facebook.runs import RunMetrics
from app.services import facebook_orchestrator
from app.services.facebook_orchestrator import (
    ProfileConfig,
    _discover_active,
    _load_profiles,
    _merge_public_profiles,
    _persist_profile_country,
)

pytestmark = pytest.mark.contract


def test_profile_config_preserves_defaults_names_and_recovery_bounds() -> None:
    profile = ProfileConfig.from_dict(
        {
            "octo_profile_uuid": "12345678-profile-id",
            "label": "Spain Mobile / Main",
            "failed_recovery_calibration_passes": 99,
        }
    )

    assert profile.enabled is True
    assert profile.expected_country is None
    assert profile.display_name == "Spain Mobile / Main"
    assert profile.storage_name == "spain_mobile_main_12345678"
    assert profile.failed_recovery_calibration_passes == 3


def test_public_discovery_deduplicates_and_does_not_adopt_proxy_geo(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    profiles_path = tmp_path / "profiles.json"
    profiles_path.write_text('{"profiles": []}', encoding="utf-8")
    monkeypatch.setattr(
        facebook_orchestrator,
        "_octo_public_profiles",
        lambda _token, **_kwargs: [
            {
                "uuid": "public-profile",
                "title": "Public profile",
                "proxy": {"country": "TR", "password": "must-not-persist"},
                "extra_info": {"geo": "Turkey"},
            }
        ],
    )

    assert _merge_public_profiles(profiles_path, token="secret", enable_new=True) == 1
    assert _merge_public_profiles(profiles_path, token="secret", enable_new=True) == 0

    payload = json.loads(profiles_path.read_text(encoding="utf-8"))
    assert payload == {
        "profiles": [
            {
                "octo_profile_uuid": "public-profile",
                "label": "Public profile",
                "expected_country": None,
                "enabled": True,
                "no_country_filter": False,
                "calibration_ads_json": [],
                "quality_guard": False,
                "failed_recovery_calibration_passes": 1,
            }
        ]
    }


def test_local_active_discovery_is_authority_for_geo_and_adds_once(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    profiles_path = tmp_path / "profiles.json"
    profiles_path.write_text(
        '{"profiles":[{"octo_profile_uuid":"known"}]}',
        encoding="utf-8",
    )
    active = [
        {"uuid": "known", "connection_data": {"country": "Canada"}},
        {
            "uuid": "new-local",
            "title": "Local Spain",
            "connection_data": {"country": "Spain", "ip": "203.0.113.4"},
        },
    ]
    monkeypatch.setattr(
        facebook_orchestrator,
        "_octo_local_get",
        lambda *_args: active,
    )
    args = SimpleNamespace(
        profiles_json=str(profiles_path),
        octo_host="127.0.0.1",
        octo_port=58888,
        enable_new=True,
    )

    assert _discover_active(args) == 0
    assert _discover_active(args) == 0

    profiles = _load_profiles(profiles_path)
    assert [profile.octo_profile_uuid for profile in profiles] == [
        "known",
        "new-local",
    ]
    assert profiles[1].expected_country == "Spain"
    assert "203.0.113.4" not in profiles_path.read_text(encoding="utf-8")


def test_country_adoption_is_write_once_and_unknown_geo_is_not_invented(
    tmp_path: Path,
) -> None:
    profiles_path = tmp_path / "profiles.json"
    profiles_path.write_text(
        '{"profiles":[{"octo_profile_uuid":"profile","expected_country":null}]}',
        encoding="utf-8",
    )

    _persist_profile_country(profiles_path, "profile", "Spain")
    _persist_profile_country(profiles_path, "profile", "Canada")

    assert _load_profiles(profiles_path)[0].expected_country == "Spain"
    assert normalize_country("TR") == "Turkey"
    assert normalize_country("  Serbia  ") == "Serbia"
    assert normalize_country("   ") is None


def test_baseline_only_uses_comparable_good_profile_windows() -> None:
    policy = CalibrationPolicy(
        min_elapsed_seconds=600,
        min_good_ads_for_baseline=10,
        min_good_targets_for_baseline=5,
    )
    healthy = RunMetrics(
        run_dir="healthy",
        profile_uuid="profile",
        profile_country="Spain",
        geo_observed=True,
        geo_match=True,
        elapsed_seconds=900,
        ads_total=30,
        target_ads=10,
        ads_per_hour=120,
        octo_headless=False,
    )
    wrong_mode = RunMetrics(
        **{
            **healthy.to_dict(),
            "run_dir": "headless",
            "ads_per_hour": 999,
            "octo_headless": True,
        }
    )
    infrastructure_failure = RunMetrics(
        **{
            **healthy.to_dict(),
            "run_dir": "timeout",
            "ads_per_hour": 1,
            "stop_reason": "octo_start_error",
        }
    )

    baseline = baseline_from_history(
        [wrong_mode, infrastructure_failure, healthy],
        policy=policy,
    )

    assert baseline.sample_count == 1
    assert baseline.source_run_dirs == ["healthy"]
    assert baseline.ads_per_hour == 120
    assert baseline.octo_headless is False

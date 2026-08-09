from __future__ import annotations

import pytest

from app.facebook.collection import interest_safety_violations

pytestmark = pytest.mark.unit


def valid_summary() -> dict[str, object]:
    return {
        "interest_safe_mode": True,
        "resolve_enabled": False,
        "active_actions": {
            "cta_click_attempts": 0,
            "video_play_attempts": 0,
            "comment_open_attempts": 0,
        },
        "passive_media_guard": {
            "installed": True,
            "init_script_installed": True,
            "media_route_installed": True,
        },
    }


def test_valid_passive_collection_has_no_violations() -> None:
    assert interest_safety_violations(valid_summary(), [{"screenshot": "ad.png"}]) == []


def test_missing_summary_short_circuits_artifact_checks() -> None:
    assert interest_safety_violations([], None) == ["missing_summary"]


def test_summary_violations_preserve_pipeline_audit_order() -> None:
    summary = {
        "interest_safe_mode": False,
        "resolve_enabled": True,
        "active_actions": {
            "cta_click_attempts": "2",
            "comment_open_attempts": -4,
        },
        "passive_media_guard": {
            "installed": False,
            "media_route_installed": 1,
        },
    }

    assert interest_safety_violations(summary, None) == [
        "safe_mode_not_confirmed",
        "landing_resolution_enabled",
        "nonzero_cta_click_attempts",
        "missing_video_play_attempts",
        "media_guard_installed_false",
        "media_guard_init_script_installed_false",
        "media_guard_media_route_installed_false",
        "missing_ads_file",
    ]


def test_malformed_audit_sections_are_rejected() -> None:
    summary = valid_summary()
    summary["active_actions"] = []
    summary["passive_media_guard"] = None

    assert interest_safety_violations(summary, []) == [
        "missing_active_action_audit",
        "missing_passive_media_guard",
    ]


def test_malformed_action_counters_keep_legacy_zero_coercion() -> None:
    summary = valid_summary()
    summary["active_actions"] = {
        "cta_click_attempts": "not-an-integer",
        "video_play_attempts": object(),
        "comment_open_attempts": None,
    }

    assert interest_safety_violations(summary, []) == []


def test_forbidden_artifacts_are_reported_once_in_stable_order() -> None:
    ads = [
        {"video": "first.mp4", "landing_full": "https://first.example"},
        {"video": "second.mp4", "landing_archive": "landing.zip"},
        "malformed",
    ]

    assert interest_safety_violations(valid_summary(), ads) == [
        "passive_ad_contains_landing_full",
        "passive_ad_contains_landing_archive",
        "passive_ad_contains_video",
    ]

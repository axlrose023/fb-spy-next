from __future__ import annotations

from typing import Any

import pytest

from app.facebook.orchestration import (
    OrchestrationState,
    ProfileCycleSchedule,
    ProfileState,
    orchestration_state_from_dict,
    orchestration_state_to_dict,
    profile_resume_schedule,
    profile_state_recovery_active,
    schedule_from_dict,
    schedule_to_dict,
    to_nonnegative_int,
)

pytestmark = pytest.mark.unit


def test_schedule_serialization_preserves_existing_json_shape() -> None:
    schedule = ProfileCycleSchedule(
        kind="recovery_burst",
        rest_seconds=0.0,
        recovery_burst_count=2,
        recovery_attempt=2,
        recovery_active=True,
    )

    payload = schedule_to_dict(schedule)

    assert payload == {
        "kind": "recovery_burst",
        "rest_seconds": 0.0,
        "recovery_burst_count": 2,
        "recovery_attempt": 2,
        "recovery_active": True,
    }
    assert schedule_from_dict(payload) == schedule


@pytest.mark.parametrize(
    ("raw", "default_rest", "expected"),
    [
        (
            {},
            2700,
            ProfileCycleSchedule(kind="normal", rest_seconds=2700),
        ),
        (
            {"recovery_burst_count": "3"},
            2700,
            ProfileCycleSchedule(
                kind="normal",
                rest_seconds=2700,
                recovery_burst_count=3,
            ),
        ),
        (
            {
                "recovery_burst_count": 9,
                "last_schedule": {
                    "kind": "recovery_burst_rest",
                    "rest_seconds": "invalid",
                    "recovery_attempt": "4",
                },
            },
            1800,
            ProfileCycleSchedule(
                kind="recovery_burst_rest",
                rest_seconds=1800,
                recovery_burst_count=9,
                recovery_attempt=4,
                recovery_active=True,
            ),
        ),
        (
            {
                "last_schedule": {
                    "kind": "infrastructure_retry",
                    "rest_seconds": -10,
                    "recovery_burst_count": -2,
                    "recovery_active": True,
                }
            },
            300,
            ProfileCycleSchedule(
                kind="infrastructure_retry",
                rest_seconds=0,
                recovery_active=True,
            ),
        ),
    ],
)
def test_resume_schedule_accepts_legacy_and_malformed_values(
    raw: dict[str, Any],
    default_rest: float,
    expected: ProfileCycleSchedule,
) -> None:
    assert profile_resume_schedule(raw, default_rest_seconds=default_rest) == expected


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        (None, 0),
        ("", 0),
        (-3, 0),
        ("7", 7),
        (3.9, 3),
        ("invalid", 0),
    ],
)
def test_nonnegative_integer_keeps_legacy_coercion(
    value: object, expected: int
) -> None:
    assert to_nonnegative_int(value) == expected


def test_recovery_active_supports_burst_count_and_legacy_schedule_kind() -> None:
    assert profile_state_recovery_active({"recovery_burst_count": "1"})
    assert profile_state_recovery_active(
        {"last_schedule": {"kind": "recovery_burst_rest"}}
    )
    assert not profile_state_recovery_active(
        {"last_schedule": {"kind": "normal", "recovery_active": False}}
    )


def test_state_round_trip_preserves_unknown_root_and_profile_fields() -> None:
    raw = {
        "schema_marker": "legacy-v0",
        "profiles": {
            "spain": {
                "octo_profile_uuid": "spain",
                "label": "Spain",
                "expected_country": "Spain",
                "runs": [{"at": "2026-08-09T10:00:00+00:00"}],
                "calibrations": [{"summary": {"visited": 10}}],
                "recovery_burst_count": 1,
                "last_schedule": {
                    "kind": "recovery_burst",
                    "rest_seconds": 0,
                    "recovery_burst_count": 1,
                    "recovery_attempt": 1,
                    "recovery_active": True,
                },
                "custom_profile_flag": {"keep": True},
            }
        },
    }

    state = orchestration_state_from_dict(raw)
    encoded = orchestration_state_to_dict(state)

    assert isinstance(state, OrchestrationState)
    assert state.profiles["spain"].recovery_active
    assert encoded["schema_marker"] == "legacy-v0"
    assert encoded["profiles"]["spain"]["custom_profile_flag"] == {"keep": True}
    assert encoded["profiles"]["spain"]["last_schedule"] == {
        "kind": "recovery_burst",
        "rest_seconds": 0.0,
        "recovery_burst_count": 1,
        "recovery_attempt": 1,
        "recovery_active": True,
    }


def test_invalid_state_payload_decodes_to_empty_typed_state() -> None:
    assert orchestration_state_from_dict(None) == OrchestrationState()
    assert orchestration_state_from_dict({"profiles": []}) == OrchestrationState()


def test_explicit_state_models_are_serializable_without_adapter_dependencies() -> None:
    state = OrchestrationState(
        profiles={
            "profile": ProfileState(
                octo_profile_uuid="profile",
                runs=({"metrics": {"ads_total": 10}},),
            )
        }
    )

    assert orchestration_state_to_dict(state)["profiles"]["profile"]["runs"] == [
        {"metrics": {"ads_total": 10}}
    ]

from __future__ import annotations

from dataclasses import asdict
from typing import Any

from .models import (
    OrchestrationState,
    ProfileCycleSchedule,
    ProfileState,
)

PROFILE_FIELDS = {
    "octo_profile_uuid",
    "label",
    "expected_country",
    "runs",
    "calibrations",
    "recovery_burst_count",
    "last_schedule",
    "baseline",
    "updated_at",
}


def to_nonnegative_int(value: Any) -> int:
    try:
        return max(0, int(value or 0))
    except (TypeError, ValueError):
        return 0


def schedule_to_dict(schedule: ProfileCycleSchedule) -> dict[str, Any]:
    return asdict(schedule)


def schedule_from_dict(
    raw: Any,
    *,
    default_rest_seconds: float = 0.0,
) -> ProfileCycleSchedule | None:
    if not isinstance(raw, dict):
        return None
    try:
        rest_seconds = max(0.0, float(raw.get("rest_seconds", 0.0)))
    except (TypeError, ValueError):
        rest_seconds = max(0.0, default_rest_seconds)
    recovery_attempt = raw.get("recovery_attempt")
    return ProfileCycleSchedule(
        kind=str(raw.get("kind") or "normal"),
        rest_seconds=rest_seconds,
        recovery_burst_count=to_nonnegative_int(raw.get("recovery_burst_count")),
        recovery_attempt=(
            to_nonnegative_int(recovery_attempt)
            if recovery_attempt is not None
            else None
        ),
        recovery_active=bool(
            raw.get("recovery_active")
            or raw.get("kind") in {"recovery_burst", "recovery_burst_rest"}
        ),
    )


def profile_resume_schedule(
    raw_profile: Any,
    *,
    default_rest_seconds: float,
) -> ProfileCycleSchedule:
    profile = raw_profile if isinstance(raw_profile, dict) else {}
    raw_schedule = profile.get("last_schedule")
    if not isinstance(raw_schedule, dict):
        return ProfileCycleSchedule(
            kind="normal",
            rest_seconds=max(0.0, default_rest_seconds),
            recovery_burst_count=to_nonnegative_int(
                profile.get("recovery_burst_count")
            ),
        )
    schedule = schedule_from_dict(
        {
            **raw_schedule,
            "recovery_burst_count": raw_schedule.get(
                "recovery_burst_count",
                profile.get("recovery_burst_count"),
            ),
        },
        default_rest_seconds=default_rest_seconds,
    )
    if schedule is None:
        raise AssertionError("dict schedule must be decodable")
    return schedule


def profile_state_recovery_active(raw_profile: Any) -> bool:
    profile = raw_profile if isinstance(raw_profile, dict) else {}
    if to_nonnegative_int(profile.get("recovery_burst_count")) > 0:
        return True
    schedule = profile.get("last_schedule")
    if not isinstance(schedule, dict):
        return False
    return bool(
        schedule.get("recovery_active")
        or schedule.get("kind") in {"recovery_burst", "recovery_burst_rest"}
    )


def profile_state_from_dict(raw: Any, *, profile_uuid: str = "") -> ProfileState:
    payload = raw if isinstance(raw, dict) else {}
    runs = tuple(item for item in payload.get("runs", []) if isinstance(item, dict))
    calibrations = tuple(
        item for item in payload.get("calibrations", []) if isinstance(item, dict)
    )
    baseline = payload.get("baseline")
    return ProfileState(
        octo_profile_uuid=str(payload.get("octo_profile_uuid") or profile_uuid),
        label=str(payload.get("label") or ""),
        expected_country=(
            str(payload["expected_country"])
            if payload.get("expected_country") is not None
            else None
        ),
        runs=runs,
        calibrations=calibrations,
        recovery_burst_count=to_nonnegative_int(payload.get("recovery_burst_count")),
        last_schedule=schedule_from_dict(payload.get("last_schedule")),
        baseline=dict(baseline) if isinstance(baseline, dict) else None,
        updated_at=(
            str(payload["updated_at"])
            if payload.get("updated_at") is not None
            else None
        ),
        extras={
            key: value for key, value in payload.items() if key not in PROFILE_FIELDS
        },
    )


def profile_state_to_dict(profile: ProfileState) -> dict[str, Any]:
    payload = {
        **profile.extras,
        "octo_profile_uuid": profile.octo_profile_uuid,
        "label": profile.label,
        "expected_country": profile.expected_country,
        "runs": [dict(item) for item in profile.runs],
        "calibrations": [dict(item) for item in profile.calibrations],
        "recovery_burst_count": profile.recovery_burst_count,
    }
    if profile.last_schedule is not None:
        payload["last_schedule"] = schedule_to_dict(profile.last_schedule)
    if profile.baseline is not None:
        payload["baseline"] = dict(profile.baseline)
    if profile.updated_at is not None:
        payload["updated_at"] = profile.updated_at
    return payload


def orchestration_state_from_dict(raw: Any) -> OrchestrationState:
    payload = raw if isinstance(raw, dict) else {}
    raw_profiles = payload.get("profiles")
    profiles = {
        str(profile_uuid): profile_state_from_dict(
            profile,
            profile_uuid=str(profile_uuid),
        )
        for profile_uuid, profile in (
            raw_profiles.items() if isinstance(raw_profiles, dict) else ()
        )
    }
    return OrchestrationState(
        profiles=profiles,
        extras={key: value for key, value in payload.items() if key != "profiles"},
    )


def orchestration_state_to_dict(state: OrchestrationState) -> dict[str, Any]:
    return {
        **state.extras,
        "profiles": {
            profile_uuid: profile_state_to_dict(profile)
            for profile_uuid, profile in state.profiles.items()
        },
    }

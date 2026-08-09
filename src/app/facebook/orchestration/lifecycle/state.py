from __future__ import annotations

from typing import Any

from app.facebook.profiles import Profile


def new_profile_state(profile: Profile) -> dict[str, Any]:
    return {
        "octo_profile_uuid": profile.octo_profile_uuid,
        "label": profile.label,
        "expected_country": profile.expected_country,
        "runs": [],
        "calibrations": [],
    }


def calibration_timestamp(raw: dict[str, Any]) -> Any:
    return raw.get("finished_at") or raw.get("started_at") or raw.get("at")

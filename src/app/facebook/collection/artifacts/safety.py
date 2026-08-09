from __future__ import annotations

from typing import Any

ACTIVE_ACTIONS = (
    "cta_click_attempts",
    "video_play_attempts",
    "comment_open_attempts",
)
MEDIA_GUARD_FIELDS = (
    "installed",
    "init_script_installed",
    "media_route_installed",
)
FORBIDDEN_PASSIVE_ARTIFACTS = (
    "landing_full",
    "landing_clean",
    "landing_screenshot",
    "landing_archive",
    "video",
)


def interest_safety_violations(summary: Any, ads: Any) -> list[str]:
    if not isinstance(summary, dict):
        return ["missing_summary"]

    violations: list[str] = []
    if summary.get("interest_safe_mode") is not True:
        violations.append("safe_mode_not_confirmed")
    if summary.get("resolve_enabled") is not False:
        violations.append("landing_resolution_enabled")
    _audit_actions(summary.get("active_actions"), violations)
    _audit_media_guard(summary.get("passive_media_guard"), violations)

    if not isinstance(ads, list):
        violations.append("missing_ads_file")
        return violations
    for artifact in FORBIDDEN_PASSIVE_ARTIFACTS:
        if any(isinstance(ad, dict) and bool(ad.get(artifact)) for ad in ads):
            violations.append(f"passive_ad_contains_{artifact}")
    return violations


def _audit_actions(raw: Any, violations: list[str]) -> None:
    if not isinstance(raw, dict):
        violations.append("missing_active_action_audit")
        return
    for action in ACTIVE_ACTIONS:
        if action not in raw:
            violations.append(f"missing_{action}")
        elif _nonnegative_int(raw.get(action)) != 0:
            violations.append(f"nonzero_{action}")


def _audit_media_guard(raw: Any, violations: list[str]) -> None:
    if not isinstance(raw, dict):
        violations.append("missing_passive_media_guard")
        return
    for field in MEDIA_GUARD_FIELDS:
        if raw.get(field) is not True:
            violations.append(f"media_guard_{field}_false")


def _nonnegative_int(value: Any) -> int:
    try:
        return max(0, int(value or 0))
    except (TypeError, ValueError):
        return 0

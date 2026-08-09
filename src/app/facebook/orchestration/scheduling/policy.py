from __future__ import annotations

from dataclasses import replace
from typing import Any

from app.facebook.calibration import CalibrationDecision, CalibrationPolicy
from app.facebook.runs import RunMetrics

from ..models import ProfileCycleSchedule, RecoverySchedulePolicy

TECHNICAL_STOP_BLOCKERS = {
    "collector_stop_reason_resolve_timeout",
    "collector_stop_reason_scroll_failed",
    "collector_stop_reason_video_timeout",
}
INFRASTRUCTURE_STOP_REASONS = {"octo_proxy_error", "octo_start_error"}
NON_FAILURE_STOP_REASONS = {"facebook_login_required", "interrupted"}


def next_profile_schedule(
    *,
    previous_burst_count: int,
    metrics: RunMetrics,
    decision: CalibrationDecision,
    calibration: dict[str, Any] | None,
    policy: RecoverySchedulePolicy,
    previous_recovery_active: bool = False,
    infrastructure_retry_required: bool = False,
) -> ProfileCycleSchedule:
    burst_count = max(0, previous_burst_count)
    recovery_active = previous_recovery_active or burst_count > 0
    normal_rest = max(0.0, policy.normal_rest_seconds)
    retry_rest = max(0.0, policy.infrastructure_retry_seconds)
    blocked_technical_stop = (
        calibration is None
        and decision.status != "healthy"
        and any(blocker in TECHNICAL_STOP_BLOCKERS for blocker in decision.blockers)
    )
    collector_failed = (
        metrics.return_code not in {None, 0}
        and metrics.stop_reason not in NON_FAILURE_STOP_REASONS
    )
    if (
        infrastructure_retry_required
        or collector_failed
        or blocked_technical_stop
        or metrics.stop_reason in INFRASTRUCTURE_STOP_REASONS
    ):
        return ProfileCycleSchedule(
            kind="infrastructure_retry",
            rest_seconds=retry_rest,
            recovery_burst_count=burst_count,
            recovery_active=recovery_active,
        )
    if calibration:
        return _schedule_after_calibration(
            burst_count=burst_count,
            recovery_active=recovery_active,
            calibration=calibration,
            decision=decision,
            policy=policy,
            normal_rest=normal_rest,
            retry_rest=retry_rest,
        )
    if decision.status == "healthy":
        burst_count = 0
        recovery_active = False
    return ProfileCycleSchedule(
        kind="normal",
        rest_seconds=normal_rest,
        recovery_burst_count=burst_count,
        recovery_active=recovery_active,
    )


def is_recovery_calibration_decision(decision: CalibrationDecision) -> bool:
    return bool(set(decision.reasons) - {"periodic_account_maintenance"})


def recovery_evaluation_policy(
    policy: CalibrationPolicy,
    *,
    recovery_active: bool,
    quality_guard: bool = False,
) -> CalibrationPolicy:
    overrides: dict[str, Any] = {
        "zero_ads_calibration_burst_limit": max(
            policy.zero_ads_calibration_burst_limit,
            policy.max_calibrations_per_24h + 1,
        ),
        "proactive_quality_drop_enabled": quality_guard,
    }
    if recovery_active:
        overrides.update(
            calibration_cooldown_seconds=0.0,
            zero_ads_calibration_cooldown_seconds=0.0,
            calibration_retry_cooldown_seconds=0.0,
        )
    return replace(policy, **overrides)


def _schedule_after_calibration(
    *,
    burst_count: int,
    recovery_active: bool,
    calibration: dict[str, Any],
    decision: CalibrationDecision,
    policy: RecoverySchedulePolicy,
    normal_rest: float,
    retry_rest: float,
) -> ProfileCycleSchedule:
    raw_summary = calibration.get("summary")
    summary: dict[str, Any] = raw_summary if isinstance(raw_summary, dict) else {}
    status = str(summary.get("status") or "")
    if status == "infrastructure_error" or summary.get("infrastructure_error"):
        return ProfileCycleSchedule(
            kind="infrastructure_retry",
            rest_seconds=retry_rest,
            recovery_burst_count=burst_count,
            recovery_active=recovery_active,
        )
    if status not in {"completed", "dry_run"}:
        return ProfileCycleSchedule(
            kind="calibration_retry",
            rest_seconds=retry_rest,
            recovery_burst_count=burst_count,
            recovery_active=recovery_active,
        )
    if not is_recovery_calibration_decision(decision):
        return ProfileCycleSchedule(
            kind="normal",
            rest_seconds=normal_rest,
            recovery_burst_count=0,
        )
    attempt = burst_count + 1
    if attempt >= max(1, policy.burst_limit):
        return ProfileCycleSchedule(
            kind="recovery_burst_rest",
            rest_seconds=normal_rest,
            recovery_burst_count=0,
            recovery_attempt=attempt,
            recovery_active=True,
        )
    return ProfileCycleSchedule(
        kind="recovery_burst",
        rest_seconds=max(0.0, policy.burst_rest_seconds),
        recovery_burst_count=attempt,
        recovery_attempt=attempt,
        recovery_active=True,
    )

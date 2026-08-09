from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

import pytest

from app.facebook.calibration import CalibrationDecision, CalibrationPolicy
from app.facebook.orchestration import (
    ProfileCycleSchedule,
    RecoverySchedulePolicy,
    next_profile_schedule,
    profile_rest_seconds,
    recovery_evaluation_policy,
    recovery_schedule_policy,
    remaining_profile_rest_seconds,
)
from app.facebook.runs import RunMetrics

pytestmark = pytest.mark.unit

DEFAULT_SCHEDULE_POLICY = RecoverySchedulePolicy(
    normal_rest_seconds=45 * 60,
    burst_limit=3,
    burst_rest_seconds=0,
    infrastructure_retry_seconds=5 * 60,
)


def decision(
    status: str,
    *,
    reasons: list[str] | None = None,
    blockers: list[str] | None = None,
) -> CalibrationDecision:
    return CalibrationDecision(
        status=status,
        should_calibrate=status == "calibrate",
        severity="high" if status == "calibrate" else "none",
        reasons=reasons or [],
        blockers=blockers or [],
    )


@pytest.mark.parametrize(
    ("metrics", "current_decision", "calibration", "retry_required", "expected"),
    [
        (
            RunMetrics(run_dir="proxy", return_code=2, stop_reason="octo_proxy_error"),
            decision("manual_review"),
            None,
            False,
            ProfileCycleSchedule("infrastructure_retry", 300),
        ),
        (
            RunMetrics(run_dir="classifier", return_code=0),
            decision("healthy"),
            None,
            True,
            ProfileCycleSchedule("infrastructure_retry", 300),
        ),
        (
            RunMetrics(run_dir="blocked", return_code=0),
            decision(
                "watch",
                blockers=["collector_stop_reason_resolve_timeout"],
            ),
            None,
            False,
            ProfileCycleSchedule("infrastructure_retry", 300),
        ),
        (
            RunMetrics(run_dir="failed-calibration", return_code=0),
            decision("calibrate", reasons=["zero_relevant_ads"]),
            {"summary": {"status": "failed"}},
            False,
            ProfileCycleSchedule("calibration_retry", 300),
        ),
        (
            RunMetrics(run_dir="maintenance", return_code=0),
            decision("calibrate", reasons=["periodic_account_maintenance"]),
            {"summary": {"status": "completed", "ok": 10}},
            False,
            ProfileCycleSchedule("normal", 2700),
        ),
        (
            RunMetrics(run_dir="healthy", return_code=0),
            decision("healthy"),
            None,
            False,
            ProfileCycleSchedule("normal", 2700),
        ),
    ],
)
def test_schedule_policy_covers_infrastructure_recovery_and_maintenance(
    metrics: RunMetrics,
    current_decision: CalibrationDecision,
    calibration: dict[str, Any] | None,
    retry_required: bool,
    expected: ProfileCycleSchedule,
) -> None:
    result = next_profile_schedule(
        previous_burst_count=0,
        metrics=metrics,
        decision=current_decision,
        calibration=calibration,
        policy=DEFAULT_SCHEDULE_POLICY,
        infrastructure_retry_required=retry_required,
    )

    assert result == expected


def test_recovery_burst_is_bounded_then_uses_normal_rest() -> None:
    current_decision = decision("calibrate", reasons=["zero_relevant_ads"])
    calibration = {"summary": {"status": "completed", "ok": 20}}
    first = next_profile_schedule(
        previous_burst_count=0,
        metrics=RunMetrics(run_dir="first", return_code=0),
        decision=current_decision,
        calibration=calibration,
        policy=DEFAULT_SCHEDULE_POLICY,
    )
    second = next_profile_schedule(
        previous_burst_count=first.recovery_burst_count,
        metrics=RunMetrics(run_dir="second", return_code=0),
        decision=current_decision,
        calibration=calibration,
        policy=DEFAULT_SCHEDULE_POLICY,
    )
    third = next_profile_schedule(
        previous_burst_count=second.recovery_burst_count,
        metrics=RunMetrics(run_dir="third", return_code=0),
        decision=current_decision,
        calibration=calibration,
        policy=DEFAULT_SCHEDULE_POLICY,
    )

    assert [first.kind, second.kind, third.kind] == [
        "recovery_burst",
        "recovery_burst",
        "recovery_burst_rest",
    ]
    assert third == ProfileCycleSchedule(
        kind="recovery_burst_rest",
        rest_seconds=2700,
        recovery_burst_count=0,
        recovery_attempt=3,
        recovery_active=True,
    )


def test_profile_rest_uses_larger_of_cycle_delay_and_profile_rest() -> None:
    assert profile_rest_seconds(cycle_sleep_seconds=60, profile_rest_minutes=15) == 900
    assert (
        profile_rest_seconds(cycle_sleep_seconds=1200, profile_rest_minutes=15) == 1200
    )


def test_recovery_schedule_input_is_normalized_at_cli_boundary() -> None:
    policy = recovery_schedule_policy(
        cycle_sleep_seconds=-1,
        profile_rest_minutes=15,
        recovery_burst_cycles=0,
        recovery_burst_rest_minutes=-3,
        infrastructure_retry_minutes=5,
    )

    assert policy == RecoverySchedulePolicy(
        normal_rest_seconds=900,
        burst_limit=1,
        burst_rest_seconds=0,
        infrastructure_retry_seconds=300,
    )


@pytest.mark.parametrize(
    ("last_run_at", "rest_seconds", "expected"),
    [
        (None, 900, 0),
        ("invalid", 900, 0),
        ("2026-07-15T17:55:00+00:00", 900, 600),
        ("2026-07-15T17:30:00+00:00", 900, 0),
        ("2026-07-15T18:05:00", 900, 900),
    ],
)
def test_remaining_rest_survives_restart_and_clock_skew(
    last_run_at: str | None,
    rest_seconds: float,
    expected: float,
) -> None:
    assert (
        remaining_profile_rest_seconds(
            last_run_at,
            rest_seconds,
            now=datetime(2026, 7, 15, 18, 0, tzinfo=UTC),
        )
        == expected
    )


def test_recovery_evaluation_removes_only_cooldowns_and_preserves_daily_cap() -> None:
    policy = CalibrationPolicy(
        calibration_cooldown_seconds=3600,
        zero_ads_calibration_cooldown_seconds=1800,
        calibration_retry_cooldown_seconds=1800,
        max_calibrations_per_24h=36,
    )

    active = recovery_evaluation_policy(
        policy,
        recovery_active=True,
        quality_guard=True,
    )

    assert active.calibration_cooldown_seconds == 0
    assert active.zero_ads_calibration_cooldown_seconds == 0
    assert active.calibration_retry_cooldown_seconds == 0
    assert active.max_calibrations_per_24h == 36
    assert active.zero_ads_calibration_burst_limit == 37
    assert active.proactive_quality_drop_enabled is True

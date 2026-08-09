from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

import pytest

from app.facebook.orchestration import (
    RecoveryCycleCoordinator,
    calibration_allows_followup,
    calibration_pass_target_cap,
    calibration_passes_for_cycle,
    calibration_targets_consumed,
    relevance_result_meaningfully_improved,
    remaining_daily_calibration_attempts,
)
from app.facebook.profiles import Profile
from app.facebook.runs import RunMetrics
from app.services.facebook_orchestrator import (
    _calibration_allows_followup as legacy_calibration_allows_followup,
)
from app.services.facebook_orchestrator import (
    _calibration_pass_target_cap as legacy_calibration_pass_target_cap,
)
from app.services.facebook_orchestrator import (
    _calibration_passes_for_cycle as legacy_calibration_passes_for_cycle,
)
from app.services.facebook_orchestrator import (
    _calibration_targets_consumed as legacy_calibration_targets_consumed,
)
from app.services.facebook_orchestrator import (
    _relevance_result_meaningfully_improved as legacy_relevance_improved,
)
from app.services.facebook_orchestrator import (
    _remaining_daily_calibration_attempts as legacy_remaining_daily_attempts,
)

pytestmark = pytest.mark.unit


def successful_record(visited: int) -> dict[str, Any]:
    return {
        "summary": {
            "status": "completed",
            "visited": visited,
        }
    }


def test_recovery_coordinator_rotates_offsets_and_splits_target_pool() -> None:
    calls: list[tuple[int, int]] = []
    logs: list[tuple[int, int, int]] = []

    def execute(target_offset: int, target_limit: int) -> dict[str, Any]:
        calls.append((target_offset, target_limit))
        return successful_record(target_limit)

    result = RecoveryCycleCoordinator().run(
        planned_passes=3,
        remaining_daily_attempts=5,
        available_targets=30,
        target_offset=7,
        min_targets=3,
        stop_requested=lambda: False,
        execute_pass=execute,
        log_followup=lambda pass_number, passes, remaining: logs.append(
            (pass_number, passes, remaining)
        ),
    )

    assert calls == [(7, 10), (17, 10), (27, 10)]
    assert logs == [(2, 3, 20), (3, 3, 10)]
    assert [record["pass_index"] for record in result.records] == [1, 2, 3]
    assert all(record["planned_passes"] == 3 for record in result.records)
    assert result.next_target_offset == 37
    assert result.remaining_targets == 0


@pytest.mark.parametrize(
    "record",
    [
        {"summary": {"status": "failed", "visited": 10}},
        {
            "summary": {
                "status": "completed",
                "visited": 10,
                "infrastructure_error": "proxy",
            }
        },
        {"summary": {"status": "completed", "visited": 0}},
    ],
)
def test_failed_or_empty_pass_stops_followup(record: dict[str, Any]) -> None:
    calls = 0

    def execute(_offset: int, _limit: int) -> dict[str, Any]:
        nonlocal calls
        calls += 1
        return record

    result = RecoveryCycleCoordinator().run(
        planned_passes=3,
        remaining_daily_attempts=3,
        available_targets=30,
        target_offset=0,
        min_targets=3,
        stop_requested=lambda: False,
        execute_pass=execute,
        log_followup=lambda _number, _passes, _remaining: None,
    )

    assert calls == 1
    assert len(result.records) == 1


def test_stop_and_minimum_target_guards_prevent_execution() -> None:
    executed = False

    def execute(_offset: int, _limit: int) -> dict[str, Any]:
        nonlocal executed
        executed = True
        return successful_record(1)

    stopped = RecoveryCycleCoordinator().run(
        planned_passes=3,
        remaining_daily_attempts=3,
        available_targets=30,
        target_offset=0,
        min_targets=3,
        stop_requested=lambda: True,
        execute_pass=execute,
        log_followup=lambda _number, _passes, _remaining: None,
    )
    below_minimum = RecoveryCycleCoordinator().run(
        planned_passes=3,
        remaining_daily_attempts=3,
        available_targets=2,
        target_offset=0,
        min_targets=3,
        stop_requested=lambda: False,
        execute_pass=execute,
        log_followup=lambda _number, _passes, _remaining: None,
    )

    assert stopped.records == ()
    assert below_minimum.records == ()
    assert executed is False


def test_daily_attempt_budget_uses_rolling_24_hour_window() -> None:
    now = datetime(2026, 8, 9, 12, tzinfo=UTC)
    timestamps = [
        (now - timedelta(hours=23)).isoformat(),
        (now - timedelta(hours=24)).isoformat(),
        (now - timedelta(hours=25)).isoformat(),
        "invalid",
    ]

    assert (
        remaining_daily_calibration_attempts(
            timestamps,
            limit=5,
            now=now,
        )
        == 3
    )


def test_recovery_pass_count_resets_when_relevance_meaningfully_improves() -> None:
    profile = Profile(
        octo_profile_uuid="profile",
        failed_recovery_calibration_passes=3,
    )
    previous = RunMetrics(
        run_dir="previous",
        profile_uuid="profile",
        target_source="relevance",
        relevance_known=True,
        relevance_classified_ads=20,
        relevant_ads=5,
        relevant_rate=0.25,
        target_per_hour=20,
    )
    improved = RunMetrics(
        run_dir="current",
        profile_uuid="profile",
        target_source="relevance",
        relevance_known=True,
        relevance_classified_ads=20,
        relevant_ads=7,
        relevant_rate=0.35,
        target_per_hour=30,
    )

    assert relevance_result_meaningfully_improved(improved, previous) is True
    assert (
        calibration_passes_for_cycle(
            profile,
            improved,
            [previous],
            recovery_active=True,
        )
        == 1
    )


def test_legacy_recovery_helper_names_are_exact_aliases() -> None:
    assert legacy_calibration_allows_followup is calibration_allows_followup
    assert legacy_calibration_pass_target_cap is calibration_pass_target_cap
    assert legacy_calibration_passes_for_cycle is calibration_passes_for_cycle
    assert legacy_calibration_targets_consumed is calibration_targets_consumed
    assert legacy_relevance_improved is relevance_result_meaningfully_improved
    assert legacy_remaining_daily_attempts is remaining_daily_calibration_attempts

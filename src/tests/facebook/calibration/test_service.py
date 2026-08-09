from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import pytest

from app.facebook.calibration import (
    CalibrationLoopPolicy,
    CalibrationService,
    CalibrationTarget,
    calibration_goals_met,
    interaction_counts,
    should_stop_after_target_result,
)

pytestmark = pytest.mark.unit


@dataclass
class StubExecutor:
    outcomes: list[dict[str, Any]]
    calls: list[tuple[str, int, int]] = field(default_factory=list)

    def execute(
        self,
        target: CalibrationTarget,
        *,
        index: int,
        total: int,
    ) -> dict[str, Any]:
        self.calls.append((target.url, index, total))
        return self.outcomes[(index - 1) % len(self.outcomes)]


class AdvancingClock:
    def __init__(self, *values: float) -> None:
        self._values = iter(values)

    def __call__(self) -> float:
        return next(self._values)


def target(name: str) -> CalibrationTarget:
    return CalibrationTarget(url=f"https://example.test/{name}")


def successful_result(action: dict[str, Any] | None = None) -> dict[str, Any]:
    return {
        "ok": True,
        "view": {"status": "viewing"},
        "actions": [action] if action else [],
    }


def test_service_visits_each_target_once_and_records_each_result() -> None:
    executor = StubExecutor([successful_result()])
    recorded: list[dict[str, Any]] = []

    result = CalibrationService(executor, record_result=recorded.append).run(
        [target("one"), target("two")],
        CalibrationLoopPolicy(min_interactions=0),
    )

    assert executor.calls == [
        ("https://example.test/one", 1, 2),
        ("https://example.test/two", 2, 2),
    ]
    assert recorded == list(result.results)
    assert result.termination == "targets_exhausted"
    assert (result.ok, result.failed, result.successful) == (2, 0, True)


def test_service_stops_when_success_and_interaction_goals_are_met() -> None:
    executor = StubExecutor(
        [successful_result({"action": "reaction", "status": "clicked"})]
    )

    result = CalibrationService(executor).run(
        [target("one"), target("two")],
        CalibrationLoopPolicy(min_successful_targets=1, min_interactions=1),
    )

    assert len(executor.calls) == 1
    assert result.termination == "goals_met"
    assert result.successful is True


def test_service_repeats_targets_until_session_deadline() -> None:
    executor = StubExecutor([successful_result()])
    clock = AdvancingClock(100.0, 100.0, 101.0, 102.0, 106.0)

    result = CalibrationService(executor, monotonic=clock).run(
        [target("one"), target("two")],
        CalibrationLoopPolicy(
            session_seconds=5.0,
            repeat_targets_until_deadline=True,
            min_interactions=0,
        ),
    )

    assert [call[0] for call in executor.calls] == [
        "https://example.test/one",
        "https://example.test/two",
        "https://example.test/one",
    ]
    assert result.termination == "deadline"


def test_infrastructure_error_stops_batch_but_normal_failure_does_not() -> None:
    executor = StubExecutor(
        [
            {"ok": False, "error": "post missing", "actions": []},
            {
                "ok": False,
                "error": "proxy failed",
                "infrastructure_error": True,
                "actions": [],
            },
            successful_result(),
        ]
    )

    result = CalibrationService(executor).run(
        [target("one"), target("two"), target("three")],
        CalibrationLoopPolicy(min_interactions=0),
    )

    assert len(executor.calls) == 2
    assert result.termination == "infrastructure_error"
    assert result.infrastructure_error == "proxy failed"
    assert result.successful is False


def test_transient_navigation_error_can_continue_but_closed_context_cannot() -> None:
    policy = CalibrationLoopPolicy(continue_on_target_navigation_error=True)

    assert not should_stop_after_target_result(
        {
            "infrastructure_error": True,
            "transient_navigation_error": True,
        },
        policy,
    )
    assert should_stop_after_target_result(
        {
            "infrastructure_error": True,
            "transient_navigation_error": True,
            "browser_context_closed": True,
        },
        policy,
    )


def test_comment_interval_extends_target_goal_only_when_pool_can_reach_it() -> None:
    results = [successful_result() for _ in range(5)]
    results[0]["actions"] = [{"action": "reaction", "status": "clicked"}]
    policy = CalibrationLoopPolicy(
        min_successful_targets=3,
        min_interactions=1,
        comment_every=5,
        max_comments=1,
    )

    assert not calibration_goals_met(results[:3], policy, targets_available=5)
    assert calibration_goals_met(results, policy, targets_available=5)
    assert calibration_goals_met(results[:3], policy, targets_available=4)


def test_interaction_accounting_preserves_funnel_and_existing_action_semantics() -> (
    None
):
    counts = interaction_counts(
        [
            {
                "ok": True,
                "actions": [
                    {"action": "reaction", "status": "already_active"},
                    {"action": "follow", "status": "clicked"},
                    {
                        "action": "offer_funnel",
                        "status": "success_confirmed",
                        "opening": "direct_offer",
                        "form_detected": True,
                        "form_submitted": True,
                    },
                ],
            }
        ]
    )

    assert counts["successful"] == 2
    assert counts["satisfied"] == 3
    assert counts["already_active"] == 1
    assert counts["funnel_success_confirmed"] == 1
    assert counts["direct_offer_fallback"] == 1


def test_empty_target_batch_is_a_success_when_no_minimums_are_required() -> None:
    result = CalibrationService(StubExecutor([successful_result()])).run(
        [],
        CalibrationLoopPolicy(min_interactions=0),
    )

    assert result.results == ()
    assert result.termination == "targets_exhausted"
    assert result.successful is True

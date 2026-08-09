from __future__ import annotations

import time

from .accounting import (
    calibration_goals_met,
    interaction_counts,
    should_stop_after_target_result,
)
from .contracts import (
    CalibrationResultRecorder,
    CalibrationTargetExecutor,
    MonotonicClock,
    Sleeper,
    StopRequested,
)
from .models import CalibrationLoopPolicy, CalibrationRunResult
from .planning import CalibrationTarget


class CalibrationService:
    def __init__(
        self,
        executor: CalibrationTargetExecutor,
        *,
        record_result: CalibrationResultRecorder | None = None,
        stop_requested: StopRequested | None = None,
        monotonic: MonotonicClock = time.monotonic,
        sleep: Sleeper | None = None,
    ) -> None:
        self._executor = executor
        self._record_result = record_result or _ignore_result
        self._stop_requested = stop_requested or _never_stop
        self._monotonic = monotonic
        self._sleep = sleep or _sleep

    def run(
        self,
        targets: list[CalibrationTarget],
        policy: CalibrationLoopPolicy,
    ) -> CalibrationRunResult:
        results: list[dict[str, object]] = []
        deadline = (
            self._monotonic() + policy.session_seconds if policy.has_deadline else None
        )
        attempt_index = 0
        termination = "targets_exhausted"

        while True:
            termination = self._pre_attempt_termination(
                policy,
                deadline=deadline,
                attempt_index=attempt_index,
                target_count=len(targets),
            )
            if termination:
                break

            target = targets[attempt_index % len(targets)]
            attempt_index += 1
            result = self._executor.execute(
                target,
                index=attempt_index,
                total=len(targets),
            )
            results.append(result)
            self._record_result(result)

            if should_stop_after_target_result(result, policy):
                termination = "infrastructure_error"
                break
            if not policy.repeats_targets and calibration_goals_met(
                results,
                policy,
                targets_available=len(targets),
            ):
                termination = "goals_met"
                break
            if policy.pause_between_targets > 0 and (
                deadline is None or self._monotonic() < deadline
            ):
                self._sleep(policy.pause_between_targets)

        return _run_result(results, policy, termination)

    def _pre_attempt_termination(
        self,
        policy: CalibrationLoopPolicy,
        *,
        deadline: float | None,
        attempt_index: int,
        target_count: int,
    ) -> str:
        if self._stop_requested():
            return "stop_requested"
        if deadline is not None and self._monotonic() >= deadline:
            return "deadline"
        if target_count == 0 or (
            attempt_index >= target_count and not policy.repeats_targets
        ):
            return "targets_exhausted"
        return ""


def _run_result(
    results: list[dict[str, object]],
    policy: CalibrationLoopPolicy,
    termination: str,
) -> CalibrationRunResult:
    typed_results = list(results)
    counts = interaction_counts(typed_results)
    ok = sum(1 for result in typed_results if result.get("ok"))
    failed = len(typed_results) - ok
    target_goal_met = (
        ok >= policy.min_successful_targets
        if policy.min_successful_targets > 0
        else failed == 0
    )
    infrastructure_error = next(
        (
            _error_text(result.get("error"))
            for result in typed_results
            if result.get("infrastructure_error")
        ),
        None,
    )
    return CalibrationRunResult(
        results=tuple(typed_results),
        interactions=counts,
        target_goal_met=target_goal_met,
        interaction_goal_met=counts["successful"] >= policy.min_interactions,
        infrastructure_error=infrastructure_error,
        termination=termination,
    )


def _ignore_result(_result: dict[str, object]) -> None:
    return None


def _never_stop() -> bool:
    return False


def _sleep(seconds: float) -> None:
    time.sleep(seconds)


def _error_text(value: object) -> str | None:
    if value is None or isinstance(value, str):
        return value
    return str(value)

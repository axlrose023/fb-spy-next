from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from app.facebook.calibration import (
    CalibrationDecision,
    CalibrationPolicy,
    baseline_from_history,
    evaluate_calibration_need,
)
from app.facebook.profiles import MetricBaseline
from app.facebook.runs import RunMetrics

from ..contracts import ProfileStateReader
from ..scheduling import recovery_evaluation_policy


@dataclass(frozen=True, slots=True)
class ProfileEvaluation:
    decision: CalibrationDecision
    history: tuple[RunMetrics, ...]
    baseline: MetricBaseline
    calibration_timestamps: tuple[str, ...]
    calibration_attempt_timestamps: tuple[str, ...]
    calibration_target_offset: int
    recovery_burst_count: int
    recovery_active: bool


class ProfileEvaluationService:
    def __init__(self, state: ProfileStateReader) -> None:
        self._state = state

    def evaluate(
        self,
        profile_uuid: str,
        metrics: RunMetrics,
        policy: CalibrationPolicy,
        *,
        quality_guard: bool = False,
        load_recovery_context: bool = True,
        exclude_run_dir: str | None = None,
    ) -> ProfileEvaluation:
        history, baseline, calibration_timestamps = self._state.profile_history(
            profile_uuid
        )
        if exclude_run_dir is not None:
            history, baseline_contains_excluded = _exclude_run(
                history,
                baseline,
                exclude_run_dir,
            )
        else:
            baseline_contains_excluded = False
        recovery_burst_count = 0
        recovery_active = False
        calibration_target_offset = 0
        if load_recovery_context:
            recovery_burst_count = self._state.profile_recovery_burst_count(
                profile_uuid
            )
            recovery_active = self._state.profile_recovery_evaluation_active(
                profile_uuid
            )
        calibration_attempt_timestamps = self._state.profile_calibration_attempts(
            profile_uuid
        )
        if load_recovery_context:
            calibration_target_offset = self._state.profile_calibration_target_offset(
                profile_uuid
            )
        evaluation_policy = recovery_evaluation_policy(
            policy,
            recovery_active=recovery_active,
            quality_guard=quality_guard,
        )
        if baseline.sample_count <= 0 or baseline_contains_excluded:
            baseline = baseline_from_history(history, policy=policy)
        calibration_values: list[str | datetime] = []
        calibration_values.extend(calibration_timestamps)
        calibration_attempt_values: list[str | datetime] = []
        calibration_attempt_values.extend(calibration_attempt_timestamps)
        decision = evaluate_calibration_need(
            metrics,
            history=history,
            baseline=baseline,
            policy=evaluation_policy,
            last_calibration_at=(
                calibration_timestamps[-1] if calibration_timestamps else None
            ),
            calibration_timestamps=calibration_values,
            calibration_attempt_timestamps=calibration_attempt_values,
        )
        return ProfileEvaluation(
            decision=decision,
            history=tuple(history),
            baseline=baseline,
            calibration_timestamps=tuple(calibration_timestamps),
            calibration_attempt_timestamps=tuple(calibration_attempt_timestamps),
            calibration_target_offset=calibration_target_offset,
            recovery_burst_count=recovery_burst_count,
            recovery_active=recovery_active,
        )


def _exclude_run(
    history: list[RunMetrics],
    baseline: MetricBaseline,
    run_dir: str,
) -> tuple[list[RunMetrics], bool]:
    excluded_path = _resolved_path(run_dir)
    filtered = [
        item for item in history if _resolved_path(item.run_dir) != excluded_path
    ]
    baseline_contains_excluded = any(
        _resolved_path(source_run_dir) == excluded_path
        for source_run_dir in baseline.source_run_dirs
    )
    return filtered, baseline_contains_excluded


def _resolved_path(value: str) -> Path:
    return Path(value).expanduser().resolve()

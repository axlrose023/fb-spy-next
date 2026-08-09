from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any, Protocol

from app.facebook.calibration import CalibrationDecision, CalibrationPolicy
from app.facebook.profiles import Profile
from app.facebook.runs import RunMetrics

from ..contracts import ProfileStateWriter
from ..models import ProfileCycleSchedule, RecoverySchedulePolicy
from .evaluation import ProfileEvaluation
from .pipeline import CalibrationTransition, CollectionPipelineState
from .recovery import (
    RecoveryCycleCoordinator,
    calibration_passes_for_cycle,
    remaining_daily_calibration_attempts,
)


class ProfileEvaluator(Protocol):
    def evaluate(
        self,
        profile_uuid: str,
        metrics: RunMetrics,
        policy: CalibrationPolicy,
        *,
        quality_guard: bool = False,
    ) -> ProfileEvaluation: ...


CalibrationExecutor = Callable[[CalibrationDecision, int, int], dict[str, Any]]


@dataclass(frozen=True, slots=True)
class ProfileCycleRequest:
    profile: Profile
    metrics: RunMetrics
    policy: CalibrationPolicy
    schedule_policy: RecoverySchedulePolicy
    pipeline: CollectionPipelineState
    calibration_targets_available: int
    recovery_burst_cycles: int


@dataclass(frozen=True, slots=True)
class ProfileCycleHooks:
    write_health: Callable[[CalibrationDecision], None]
    stop_requested: Callable[[], bool]
    execute_calibration: CalibrationExecutor
    log: Callable[[str], None]


class ProfileCycleService:
    def __init__(
        self,
        evaluator: ProfileEvaluator,
        state: ProfileStateWriter,
        hooks: ProfileCycleHooks,
    ) -> None:
        self._evaluator = evaluator
        self._state = state
        self._hooks = hooks

    def run(self, request: ProfileCycleRequest) -> ProfileCycleSchedule:
        evaluation = self._evaluator.evaluate(
            request.profile.octo_profile_uuid,
            request.metrics,
            request.policy,
            quality_guard=request.profile.quality_guard,
        )
        decision = evaluation.decision
        self._hooks.write_health(decision)
        self._hooks.log(
            f"health={decision.status} "
            f"ads={request.metrics.ads_total} target={request.metrics.target_ads} "
            f"recovery={evaluation.recovery_burst_count}/"
            f"{request.recovery_burst_cycles} "
            f"reasons={','.join(decision.reasons) or '-'} "
            f"blockers={','.join(decision.blockers) or '-'}"
        )

        calibration_transition = request.pipeline.calibration_transition(
            calibration_requested=decision.should_calibrate,
            stop_requested=self._hooks.stop_requested(),
        )
        calibration_records: list[dict[str, Any]] = []
        if calibration_transition is CalibrationTransition.RUN:
            recovery_result = RecoveryCycleCoordinator().run(
                planned_passes=calibration_passes_for_cycle(
                    request.profile,
                    request.metrics,
                    list(evaluation.history),
                    recovery_active=evaluation.recovery_active,
                ),
                remaining_daily_attempts=remaining_daily_calibration_attempts(
                    list(evaluation.calibration_attempt_timestamps),
                    limit=request.policy.max_calibrations_per_24h,
                ),
                available_targets=request.calibration_targets_available,
                target_offset=evaluation.calibration_target_offset,
                min_targets=request.policy.min_calibration_targets,
                stop_requested=self._hooks.stop_requested,
                execute_pass=lambda target_offset, target_limit: (
                    self._hooks.execute_calibration(
                        decision,
                        target_offset,
                        target_limit,
                    )
                ),
                log_followup=lambda pass_number, planned_passes, remaining: (
                    self._hooks.log(
                        "recovery did not improve; "
                        f"calibration pass {pass_number}/{planned_passes} "
                        f"with {remaining} unused targets"
                    )
                ),
            )
            calibration_records = list(recovery_result.records)
        elif calibration_transition is CalibrationTransition.SKIP_PIPELINE_FAILED:
            self._hooks.log("calibration skipped: collection pipeline failed")

        return self._state.record_profile_run(
            request.profile,
            request.metrics,
            decision,
            calibrations=calibration_records,
            policy=request.policy,
            schedule_policy=request.schedule_policy,
            infrastructure_retry_required=request.pipeline.post_collection_failed,
        )

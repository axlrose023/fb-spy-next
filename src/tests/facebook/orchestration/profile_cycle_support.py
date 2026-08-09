from __future__ import annotations

from typing import Any

from app.facebook.calibration import CalibrationDecision, CalibrationPolicy
from app.facebook.orchestration import (
    CollectionPipelineState,
    ProfileCycleHooks,
    ProfileCycleRequest,
    ProfileCycleSchedule,
    ProfileEvaluation,
    RecoverySchedulePolicy,
)
from app.facebook.profiles import MetricBaseline, Profile
from app.facebook.runs import RunMetrics


def metrics(*, relevant_ads: int = 2) -> RunMetrics:
    return RunMetrics(
        run_dir="current",
        profile_uuid="profile",
        ads_total=20,
        target_ads=relevant_ads,
        relevance_known=True,
        relevance_classified_ads=20,
        relevant_ads=relevant_ads,
        relevant_rate=relevant_ads / 20,
        target_source="relevance",
        target_per_hour=float(relevant_ads),
    )


def evaluation(
    decision: CalibrationDecision,
    *,
    history: tuple[RunMetrics, ...] = (),
    attempts: tuple[str, ...] = (),
    target_offset: int = 0,
    recovery_count: int = 0,
    recovery_active: bool = False,
) -> ProfileEvaluation:
    return ProfileEvaluation(
        decision=decision,
        history=history,
        baseline=MetricBaseline(),
        calibration_timestamps=(),
        calibration_attempt_timestamps=attempts,
        calibration_target_offset=target_offset,
        recovery_burst_count=recovery_count,
        recovery_active=recovery_active,
    )


class EvaluationStub:
    def __init__(self, result: ProfileEvaluation) -> None:
        self.result = result
        self.calls: list[tuple[str, RunMetrics, CalibrationPolicy, bool]] = []

    def evaluate(
        self,
        profile_uuid: str,
        run_metrics: RunMetrics,
        policy: CalibrationPolicy,
        *,
        quality_guard: bool = False,
    ) -> ProfileEvaluation:
        self.calls.append((profile_uuid, run_metrics, policy, quality_guard))
        return self.result


class StateWriterStub:
    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []
        self.schedule = ProfileCycleSchedule(kind="normal", rest_seconds=2700)

    def record_profile_run(
        self,
        profile: Profile,
        run_metrics: RunMetrics,
        decision: CalibrationDecision,
        *,
        calibration: dict[str, Any] | None = None,
        calibrations: list[dict[str, Any]] | None = None,
        policy: CalibrationPolicy,
        schedule_policy: RecoverySchedulePolicy | None = None,
        infrastructure_retry_required: bool = False,
    ) -> ProfileCycleSchedule:
        self.calls.append(
            {
                "profile": profile,
                "metrics": run_metrics,
                "decision": decision,
                "calibration": calibration,
                "calibrations": calibrations,
                "policy": policy,
                "schedule_policy": schedule_policy,
                "infrastructure_retry_required": infrastructure_retry_required,
            }
        )
        return self.schedule

    def seed_baseline(
        self,
        profile_uuid: str,
        run_metrics: RunMetrics,
        *,
        label: str = "",
        expected_country: str | None = None,
        policy: CalibrationPolicy,
    ) -> MetricBaseline:
        raise AssertionError(
            (profile_uuid, run_metrics, label, expected_country, policy)
        )


class CycleHarness:
    def __init__(self) -> None:
        self.calls: list[tuple[Any, ...]] = []
        self.stopped = False

    def hooks(self) -> ProfileCycleHooks:
        return ProfileCycleHooks(
            write_health=lambda decision: self.calls.append(("health", decision)),
            stop_requested=lambda: self.stopped,
            execute_calibration=self.execute_calibration,
            log=lambda message: self.calls.append(("log", message)),
        )

    def execute_calibration(
        self,
        decision: CalibrationDecision,
        target_offset: int,
        target_limit: int,
    ) -> dict[str, Any]:
        self.calls.append(("calibrate", decision, target_offset, target_limit))
        return {
            "summary": {
                "status": "completed",
                "visited": target_limit,
            }
        }


def cycle_request(
    profile: Profile,
    run_metrics: RunMetrics,
    policy: CalibrationPolicy,
    *,
    pipeline: CollectionPipelineState | None = None,
    targets: int = 30,
) -> ProfileCycleRequest:
    return ProfileCycleRequest(
        profile=profile,
        metrics=run_metrics,
        policy=policy,
        schedule_policy=RecoverySchedulePolicy(
            normal_rest_seconds=2700,
            burst_limit=3,
            burst_rest_seconds=0,
            infrastructure_retry_seconds=60,
        ),
        pipeline=pipeline or CollectionPipelineState(),
        calibration_targets_available=targets,
        recovery_burst_cycles=3,
    )

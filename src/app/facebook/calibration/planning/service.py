from __future__ import annotations

from datetime import datetime

from app.facebook.profiles import MetricBaseline
from app.facebook.runs import RunMetrics

from ..models import CalibrationDecision, CalibrationPolicy
from .context import PlanningContext, build_planning_context
from .signals import collect_calibration_signals
from .timing import (
    calibration_timing_blockers,
    maintenance_calibration_due,
)


def evaluate_calibration_need(
    metrics: RunMetrics,
    *,
    history: list[RunMetrics] | None = None,
    baseline: MetricBaseline | None = None,
    policy: CalibrationPolicy | None = None,
    last_calibration_at: str | datetime | None = None,
    calibration_timestamps: list[str | datetime] | None = None,
    calibration_attempt_timestamps: list[str | datetime] | None = None,
    now: datetime | None = None,
) -> CalibrationDecision:
    context = build_planning_context(
        metrics,
        history=history,
        baseline=baseline,
        policy=policy,
        last_calibration_at=last_calibration_at,
        calibration_timestamps=calibration_timestamps,
        calibration_attempt_timestamps=calibration_attempt_timestamps,
        now=now,
    )
    collect_calibration_signals(context)
    if not context.reasons and maintenance_calibration_due(
        context.metrics,
        context.history,
        last_calibration_at=context.last_calibration_at,
        now=context.now,
        policy=context.policy,
    ):
        context.reasons.append("periodic_account_maintenance")
    context.calibration_blockers.extend(
        calibration_timing_blockers(
            context.reasons,
            last_calibration_at=context.last_calibration_at,
            attempts=context.attempts,
            history=context.history,
            now=context.now,
            policy=context.policy,
        )
    )
    return _decision_from_context(context)


def _decision_from_context(context: PlanningContext) -> CalibrationDecision:
    if context.blockers:
        status = (
            "manual_review"
            if any(
                blocker
                in {
                    "collector_return_code_2",
                    "profile_geo_mismatch",
                    "profile_geo_unknown",
                }
                or blocker.startswith("collector_return_code_")
                for blocker in context.blockers
            )
            else "watch"
        )
        return _decision(
            context,
            status=status,
            should_calibrate=False,
            severity="blocked",
            blockers=context.blockers,
        )

    if context.reasons and context.calibration_blockers:
        return _decision(
            context,
            status="watch",
            should_calibrate=False,
            severity="blocked",
            blockers=context.calibration_blockers,
        )

    if context.reasons:
        return _decision(
            context,
            status="calibrate",
            should_calibrate=True,
            severity=(
                "high"
                if "zero_ads_repeated" in context.reasons
                else "low"
                if "periodic_account_maintenance" in context.reasons
                else "medium"
            ),
            blockers=[],
        )

    status = (
        "watch"
        if context.observations
        else "healthy"
        if context.baseline_ready and context.metrics.ads_total > 0
        else "watch"
    )
    return _decision(
        context,
        status=status,
        should_calibrate=False,
        severity="ok" if status == "healthy" else "low",
        blockers=[],
    )


def _decision(
    context: PlanningContext,
    *,
    status: str,
    should_calibrate: bool,
    severity: str,
    blockers: list[str],
) -> CalibrationDecision:
    return CalibrationDecision(
        status=status,
        should_calibrate=should_calibrate,
        severity=severity,
        reasons=list(context.reasons),
        blockers=list(blockers),
        observations=list(context.observations),
        consecutive=dict(context.consecutive),
        baseline=context.baseline,
        metrics=context.metrics,
    )

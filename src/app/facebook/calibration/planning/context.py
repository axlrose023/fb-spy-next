from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime

from app.facebook.profiles import MetricBaseline, window_bucket
from app.facebook.runs import RunMetrics

from ..models import CalibrationPolicy
from .consecutive import consecutive_signals
from .timing import daily_limit_reached
from .windows import (
    is_bad_stop_reason,
    is_valid_relevance_window,
    relevance_drop_confident,
)


@dataclass(slots=True)
class PlanningContext:
    metrics: RunMetrics
    history: list[RunMetrics]
    baseline: MetricBaseline
    policy: CalibrationPolicy
    now: datetime
    last_calibration_at: str | datetime | None
    attempts: list[str | datetime]
    reasons: list[str] = field(default_factory=list)
    blockers: list[str] = field(default_factory=list)
    calibration_blockers: list[str] = field(default_factory=list)
    observations: list[str] = field(default_factory=list)
    consecutive: dict[str, int] = field(default_factory=dict)
    relevance_signal_valid: bool = False
    relevance_baseline_comparison_allowed: bool = False
    baseline_ready: bool = False
    target_baseline_ready: bool = False
    absolute_relevance_drop_confident: bool = False
    relative_relevance_drop_confident: bool = False
    soft_relevance_drop_confident: bool = False


def build_planning_context(
    metrics: RunMetrics,
    *,
    history: list[RunMetrics] | None = None,
    baseline: MetricBaseline | None = None,
    policy: CalibrationPolicy | None = None,
    last_calibration_at: str | datetime | None = None,
    calibration_timestamps: list[str | datetime] | None = None,
    calibration_attempt_timestamps: list[str | datetime] | None = None,
    now: datetime | None = None,
) -> PlanningContext:
    active_policy = policy or CalibrationPolicy()
    previous = history or []
    active_baseline = baseline or MetricBaseline()
    now_dt = now or datetime.now(UTC)
    attempts = calibration_attempt_timestamps or calibration_timestamps or []
    context = PlanningContext(
        metrics=metrics,
        history=previous,
        baseline=active_baseline,
        policy=active_policy,
        now=now_dt,
        last_calibration_at=last_calibration_at,
        attempts=attempts,
    )
    _collect_blockers(context)
    context.consecutive = consecutive_signals(
        metrics,
        previous,
        active_baseline,
        active_policy,
    )
    _evaluate_baseline(context)
    _evaluate_confidence(context)
    return context


def _collect_blockers(context: PlanningContext) -> None:
    metrics = context.metrics
    policy = context.policy
    context.relevance_signal_valid = is_valid_relevance_window(metrics, policy)
    relevance_signal_actionable = (
        context.relevance_signal_valid
        and metrics.relevance_classified_ads >= policy.min_ads_for_relevance_rate
    )
    context.relevance_baseline_comparison_allowed = (
        context.relevance_signal_valid
        and metrics.relevant_rate is not None
        and metrics.relevant_rate >= policy.minimum_healthy_relevant_rate
        and int(metrics.relevant_ads or 0) >= policy.minimum_healthy_relevant_ads
    )

    if metrics.return_code not in {None, 0}:
        context.blockers.append(f"collector_return_code_{metrics.return_code}")
    if is_bad_stop_reason(metrics.stop_reason) and not relevance_signal_actionable:
        context.blockers.append(f"collector_stop_reason_{metrics.stop_reason}")
    if not metrics.geo_observed:
        context.blockers.append("profile_geo_unknown")
    if not metrics.geo_match:
        context.blockers.append("profile_geo_mismatch")
    if metrics.elapsed_seconds is None:
        context.blockers.append("missing_elapsed_time")
    elif metrics.elapsed_seconds < policy.min_elapsed_seconds and not (
        relevance_signal_actionable
    ):
        context.blockers.append("insufficient_elapsed_time")
    if metrics.ads_total == 0 and (
        metrics.scrolls is None or metrics.scrolls < policy.min_scrolls
    ):
        context.blockers.append("insufficient_scrolls_for_zero_ads")
    if (
        metrics.calibration_targets_available is not None
        and metrics.calibration_targets_available < policy.min_calibration_targets
    ):
        context.calibration_blockers.append("not_enough_calibration_targets")
    if daily_limit_reached(context.attempts, context.now, policy):
        context.calibration_blockers.append("daily_calibration_limit")


def _evaluate_baseline(context: PlanningContext) -> None:
    metrics = context.metrics
    baseline = context.baseline
    policy = context.policy
    window_matches = (
        baseline.window_seconds is not None
        and baseline.window_seconds == window_bucket(metrics.elapsed_seconds)
        and baseline.octo_headless == metrics.octo_headless
        and baseline.collector_metric_version == metrics.collector_metric_version
    )
    context.baseline_ready = window_matches and (
        baseline.trusted or baseline.sample_count >= policy.baseline_min_samples
    )
    context.target_baseline_ready = (
        window_matches
        and baseline.target_source == metrics.target_source
        and (
            metrics.target_source != "relevance"
            or context.relevance_baseline_comparison_allowed
        )
        and (
            baseline.trusted
            or baseline.target_sample_count >= policy.baseline_min_samples
        )
    )
    if not context.baseline_ready:
        context.observations.append("baseline_learning")
    if (
        baseline.sample_count > 0
        and baseline.collector_metric_version != metrics.collector_metric_version
    ):
        context.observations.append("baseline_metric_version_mismatch")


def _evaluate_confidence(context: PlanningContext) -> None:
    metrics = context.metrics
    baseline = context.baseline
    policy = context.policy
    context.absolute_relevance_drop_confident = relevance_drop_confident(
        metrics,
        context.history,
        threshold=policy.absolute_low_relevant_rate,
        policy=policy,
    )
    context.relative_relevance_drop_confident = bool(
        context.relevance_baseline_comparison_allowed
        and baseline.relevant_rate is not None
        and relevance_drop_confident(
            metrics,
            context.history,
            threshold=baseline.relevant_rate * policy.low_target_per_hour_ratio,
            policy=policy,
        )
    )
    context.soft_relevance_drop_confident = bool(
        context.relevance_baseline_comparison_allowed
        and baseline.relevant_rate is not None
        and relevance_drop_confident(
            metrics,
            context.history,
            threshold=baseline.relevant_rate * policy.watch_drop_ratio,
            policy=policy,
        )
    )

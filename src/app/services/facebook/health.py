from __future__ import annotations

import dataclasses
import math
import statistics
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any

from app.facebook.runs.metrics import (
    RunMetrics,
)
from app.facebook.runs.metrics import (
    collect_run_metrics as collect_run_metrics,
)
from app.facebook.runs.metrics.normalization import (
    parse_datetime as _parse_datetime,
)
from app.facebook.runs.metrics.normalization import (
    safe_div as _safe_div,
)


@dataclass(frozen=True)
class MetricBaseline:
    sample_count: int = 0
    collector_metric_version: int = 1
    source_run_dirs: list[str] = field(default_factory=list)
    window_seconds: float | None = None
    octo_headless: bool | None = None
    trusted: bool = False
    target_source: str | None = None
    target_sample_count: int = 0
    ads_per_hour: float | None = None
    target_per_hour: float | None = None
    resolved_per_hour: float | None = None
    ads_per_100_scrolls: float | None = None
    target_per_100_scrolls: float | None = None
    resolved_per_100_scrolls: float | None = None
    relevant_rate: float | None = None
    landing_resolution_rate: float | None = None
    domain_diversity_rate: float | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, raw: dict[str, Any] | None) -> MetricBaseline:
        if not raw:
            return cls()
        values: dict[str, Any] = {}
        for item in dataclasses.fields(cls):
            if item.name in raw:
                values[item.name] = raw[item.name]
            elif item.default is not dataclasses.MISSING:
                values[item.name] = item.default
            elif item.default_factory is not dataclasses.MISSING:
                values[item.name] = item.default_factory()
        return cls(**values)

    @classmethod
    def from_good_runs(
        cls,
        runs: list[RunMetrics],
        *,
        max_samples: int = 8,
        min_healthy_relevant_rate: float = 0.0,
        min_healthy_relevant_ads: int = 0,
    ) -> MetricBaseline:
        if not runs:
            return cls()
        latest_window = _window_bucket(runs[-1].elapsed_seconds)
        latest_headless = runs[-1].octo_headless
        latest_metric_version = runs[-1].collector_metric_version
        comparable = [
            run
            for run in runs
            if _window_bucket(run.elapsed_seconds) == latest_window
            and run.octo_headless == latest_headless
            and run.collector_metric_version == latest_metric_version
        ]
        samples = comparable[-max(1, max_samples) :]

        def med(values: list[float | None]) -> float | None:
            cleaned = [value for value in values if value is not None]
            if not cleaned:
                return None
            return float(statistics.median(cleaned))

        relevance_samples = [
            run
            for run in samples
            if run.target_source == "relevance"
            and run.relevance_known
            and run.relevant_rate is not None
            and run.relevant_rate >= min_healthy_relevant_rate
            and int(run.relevant_ads or 0) >= min_healthy_relevant_ads
        ]
        target_samples = relevance_samples or [
            run for run in samples if run.target_source == "resolved_landings"
        ]
        target_source = target_samples[-1].target_source if target_samples else None

        return cls(
            sample_count=len(samples),
            collector_metric_version=latest_metric_version,
            source_run_dirs=[run.run_dir for run in samples],
            window_seconds=latest_window,
            octo_headless=latest_headless,
            target_source=target_source,
            target_sample_count=len(target_samples),
            ads_per_hour=med([run.ads_per_hour for run in samples]),
            target_per_hour=med([run.target_per_hour for run in target_samples]),
            resolved_per_hour=med([run.resolved_per_hour for run in samples]),
            ads_per_100_scrolls=med([run.ads_per_100_scrolls for run in samples]),
            target_per_100_scrolls=med(
                [run.target_per_100_scrolls for run in target_samples],
            ),
            resolved_per_100_scrolls=med(
                [run.resolved_per_100_scrolls for run in samples],
            ),
            relevant_rate=med([run.relevant_rate for run in relevance_samples]),
            landing_resolution_rate=med(
                [_safe_div(run.resolved_landings, run.link_ads) for run in samples]
            ),
            domain_diversity_rate=med(
                [_safe_div(run.unique_domains, run.ads_total) for run in samples]
            ),
        )


@dataclass(frozen=True)
class CalibrationPolicy:
    min_elapsed_seconds: float = 600.0
    min_scrolls: int = 80
    baseline_min_samples: int = 3
    baseline_window: int = 8
    min_good_ads_for_baseline: int = 10
    min_good_targets_for_baseline: int = 5
    zero_ads_windows: int = 2
    absolute_low_ads_windows: int = 2
    low_ratio_windows: int = 2
    watch_ratio_windows: int = 2
    soft_drop_calibration_windows: int = 3
    low_ads_per_hour_ratio: float = 0.45
    low_target_per_hour_ratio: float = 0.45
    low_scroll_density_ratio: float = 0.45
    watch_drop_ratio: float = 0.70
    immediate_drop_ratio: float = 0.70
    absolute_low_ads_per_hour: float = 12.0
    min_ads_per_hour_drop: float = 25.0
    min_target_per_hour_drop: float = 10.0
    min_ads_per_100_scrolls_drop: float = 1.0
    absolute_low_relevant_rate: float = 0.03
    minimum_healthy_relevant_rate: float = 0.75
    minimum_healthy_relevant_ads: int = 15
    min_ads_for_relevance_rate: int = 10
    min_relevance_coverage: float = 0.90
    min_relevant_rate_drop: float = 0.05
    min_relevance_classified_total: int = 50
    relevance_confidence_z: float = 1.96
    proactive_quality_drop_enabled: bool = False
    proactive_quality_drop_ratio: float = 0.97
    proactive_quality_drop_min_signals: int = 2
    proactive_quality_drop_min_classified_ads: int = 20
    calibration_cooldown_seconds: float = 60 * 60
    zero_ads_calibration_cooldown_seconds: float = 30 * 60
    zero_ads_calibration_burst_limit: int = 8
    zero_ads_calibration_backoff_seconds: float = 2 * 60 * 60
    maintenance_calibration_interval_seconds: float = 6 * 60 * 60
    maintenance_min_valid_windows: int = 3
    calibration_retry_cooldown_seconds: float = 60 * 60
    max_calibrations_per_24h: int = 24
    min_calibration_targets: int = 3
    min_successful_calibration_targets: int = 3


@dataclass(frozen=True)
class CalibrationDecision:
    status: str
    should_calibrate: bool
    severity: str
    reasons: list[str] = field(default_factory=list)
    blockers: list[str] = field(default_factory=list)
    observations: list[str] = field(default_factory=list)
    consecutive: dict[str, int] = field(default_factory=dict)
    baseline: MetricBaseline = field(default_factory=MetricBaseline)
    metrics: RunMetrics | None = None

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        if self.metrics is None:
            payload["metrics"] = None
        return payload


def is_good_baseline_candidate(
    metrics: RunMetrics,
    policy: CalibrationPolicy | None = None,
) -> bool:
    active_policy = policy or CalibrationPolicy()
    if metrics.return_code not in {None, 0}:
        return False
    if _is_bad_stop_reason(metrics.stop_reason):
        return False
    if not metrics.geo_observed:
        return False
    if not metrics.geo_match:
        return False
    if (
        metrics.elapsed_seconds is None
        or metrics.elapsed_seconds < active_policy.min_elapsed_seconds
    ):
        return False
    if metrics.ads_total < active_policy.min_good_ads_for_baseline:
        return False
    if metrics.target_ads < active_policy.min_good_targets_for_baseline:
        return False
    if metrics.ads_per_hour is None or metrics.ads_per_hour <= 0:
        return False
    return True


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
    active_policy = policy or CalibrationPolicy()
    previous = history or []
    active_baseline = baseline or MetricBaseline()
    now_dt = now or datetime.now(UTC)

    reasons: list[str] = []
    blockers: list[str] = []
    calibration_blockers: list[str] = []
    observations: list[str] = []
    relevance_signal_valid = _is_valid_relevance_observation_window(
        metrics,
        active_policy,
    )
    relevance_signal_actionable = (
        relevance_signal_valid
        and metrics.relevance_classified_ads >= active_policy.min_ads_for_relevance_rate
    )
    relevance_baseline_comparison_allowed = (
        relevance_signal_valid
        and metrics.relevant_rate is not None
        and metrics.relevant_rate >= active_policy.minimum_healthy_relevant_rate
        and int(metrics.relevant_ads or 0) >= active_policy.minimum_healthy_relevant_ads
    )

    if metrics.return_code not in {None, 0}:
        blockers.append(f"collector_return_code_{metrics.return_code}")
    if _is_bad_stop_reason(metrics.stop_reason) and not relevance_signal_actionable:
        blockers.append(f"collector_stop_reason_{metrics.stop_reason}")
    if not metrics.geo_observed:
        blockers.append("profile_geo_unknown")
    if not metrics.geo_match:
        blockers.append("profile_geo_mismatch")
    if metrics.elapsed_seconds is None:
        blockers.append("missing_elapsed_time")
    elif (
        metrics.elapsed_seconds < active_policy.min_elapsed_seconds
        and not relevance_signal_actionable
    ):
        blockers.append("insufficient_elapsed_time")
    if metrics.ads_total == 0 and (
        metrics.scrolls is None or metrics.scrolls < active_policy.min_scrolls
    ):
        blockers.append("insufficient_scrolls_for_zero_ads")
    if (
        metrics.calibration_targets_available is not None
        and metrics.calibration_targets_available
        < active_policy.min_calibration_targets
    ):
        calibration_blockers.append("not_enough_calibration_targets")

    attempts = calibration_attempt_timestamps or calibration_timestamps or []
    if _daily_limit_reached(attempts, now_dt, active_policy):
        calibration_blockers.append("daily_calibration_limit")

    consecutive = {
        "zero_ads": _consecutive_count(
            metrics,
            previous,
            lambda run: (
                _is_valid_observation_window(run, active_policy) and run.ads_total == 0
            ),
        ),
        "absolute_low_ads": _consecutive_count(
            metrics,
            previous,
            lambda run: (
                _is_valid_observation_window(run, active_policy)
                and run.ads_per_hour is not None
                and run.ads_per_hour <= active_policy.absolute_low_ads_per_hour
            ),
        ),
        "low_ads_per_hour": _consecutive_count(
            metrics,
            previous,
            lambda run: (
                _is_low_ratio(
                    run.ads_per_hour,
                    active_baseline.ads_per_hour,
                    active_policy.low_ads_per_hour_ratio,
                    active_policy.min_ads_per_hour_drop,
                )
                and _is_valid_observation_window(run, active_policy)
            ),
        ),
        "watch_ads_per_hour": _consecutive_count(
            metrics,
            previous,
            lambda run: (
                _is_low_ratio(
                    run.ads_per_hour,
                    active_baseline.ads_per_hour,
                    active_policy.watch_drop_ratio,
                )
                and _is_valid_observation_window(run, active_policy)
            ),
        ),
        "low_targets_per_hour": _consecutive_count(
            metrics,
            previous,
            lambda run: (
                _is_low_ratio(
                    run.target_per_hour,
                    active_baseline.target_per_hour,
                    active_policy.low_target_per_hour_ratio,
                    active_policy.min_target_per_hour_drop,
                )
                and _is_valid_observation_window(run, active_policy)
                and _target_baseline_comparison_allowed(run, active_policy)
            ),
        ),
        "watch_targets_per_hour": _consecutive_count(
            metrics,
            previous,
            lambda run: (
                _is_low_ratio(
                    run.target_per_hour,
                    active_baseline.target_per_hour,
                    active_policy.watch_drop_ratio,
                )
                and _is_valid_observation_window(run, active_policy)
                and _target_baseline_comparison_allowed(run, active_policy)
            ),
        ),
        "low_ads_per_scroll": _consecutive_count(
            metrics,
            previous,
            lambda run: (
                _is_low_ratio(
                    run.ads_per_100_scrolls,
                    active_baseline.ads_per_100_scrolls,
                    active_policy.low_scroll_density_ratio,
                    active_policy.min_ads_per_100_scrolls_drop,
                )
                and _is_valid_observation_window(run, active_policy)
            ),
        ),
        "watch_ads_per_scroll": _consecutive_count(
            metrics,
            previous,
            lambda run: (
                _is_low_ratio(
                    run.ads_per_100_scrolls,
                    active_baseline.ads_per_100_scrolls,
                    active_policy.watch_drop_ratio,
                )
                and _is_valid_observation_window(run, active_policy)
            ),
        ),
        "low_relevant_rate": _consecutive_count(
            metrics,
            previous,
            lambda run: (
                _is_valid_relevance_observation_window(run, active_policy)
                and run.relevance_known
                and run.relevant_rate is not None
                and run.relevant_rate < active_policy.absolute_low_relevant_rate
            ),
            same_series=_same_relevance_observation_series,
        ),
        "low_relevant_rate_vs_baseline": _consecutive_count(
            metrics,
            previous,
            lambda run: (
                _is_valid_relevance_observation_window(run, active_policy)
                and run.relevance_known
                and _target_baseline_comparison_allowed(run, active_policy)
                and _is_low_ratio(
                    run.relevant_rate,
                    active_baseline.relevant_rate,
                    active_policy.low_target_per_hour_ratio,
                    active_policy.min_relevant_rate_drop,
                )
            ),
            same_series=_same_relevance_observation_series,
        ),
        "watch_relevant_rate_vs_baseline": _consecutive_count(
            metrics,
            previous,
            lambda run: (
                _is_valid_relevance_observation_window(run, active_policy)
                and run.relevance_known
                and _target_baseline_comparison_allowed(run, active_policy)
                and _is_low_ratio(
                    run.relevant_rate,
                    active_baseline.relevant_rate,
                    active_policy.watch_drop_ratio,
                )
            ),
            same_series=_same_relevance_observation_series,
        ),
    }

    baseline_window_matches = (
        active_baseline.window_seconds is not None
        and active_baseline.window_seconds == _window_bucket(metrics.elapsed_seconds)
        and active_baseline.octo_headless == metrics.octo_headless
        and active_baseline.collector_metric_version == metrics.collector_metric_version
    )
    baseline_ready = baseline_window_matches and (
        active_baseline.trusted
        or active_baseline.sample_count >= active_policy.baseline_min_samples
    )
    target_baseline_ready = (
        baseline_window_matches
        and active_baseline.target_source == metrics.target_source
        and (
            metrics.target_source != "relevance"
            or relevance_baseline_comparison_allowed
        )
        and (
            active_baseline.trusted
            or active_baseline.target_sample_count >= active_policy.baseline_min_samples
        )
    )
    if not baseline_ready:
        observations.append("baseline_learning")
    if (
        active_baseline.sample_count > 0
        and active_baseline.collector_metric_version != metrics.collector_metric_version
    ):
        observations.append("baseline_metric_version_mismatch")

    absolute_relevance_drop_confident = _relevance_drop_confident(
        metrics,
        previous,
        threshold=active_policy.absolute_low_relevant_rate,
        policy=active_policy,
    )
    relative_relevance_drop_confident = (
        relevance_baseline_comparison_allowed
        and active_baseline.relevant_rate is not None
        and _relevance_drop_confident(
            metrics,
            previous,
            threshold=(
                active_baseline.relevant_rate * active_policy.low_target_per_hour_ratio
            ),
            policy=active_policy,
        )
    )
    soft_relevance_drop_confident = (
        relevance_baseline_comparison_allowed
        and active_baseline.relevant_rate is not None
        and _relevance_drop_confident(
            metrics,
            previous,
            threshold=(active_baseline.relevant_rate * active_policy.watch_drop_ratio),
            policy=active_policy,
        )
    )

    if consecutive["zero_ads"] >= active_policy.zero_ads_windows:
        reasons.append("zero_ads_repeated")
    if (
        "zero_ads_repeated" not in reasons
        and consecutive["absolute_low_ads"] >= active_policy.absolute_low_ads_windows
    ):
        reasons.append("absolute_low_ad_yield")

    if baseline_ready:
        if (
            _is_valid_observation_window(metrics, active_policy)
            and metrics.ads_total > 0
            and _is_low_ratio(
                metrics.ads_per_hour,
                active_baseline.ads_per_hour,
                active_policy.immediate_drop_ratio,
            )
        ):
            reasons.append("ad_yield_30pct_drop")
        if consecutive["low_ads_per_hour"] >= active_policy.low_ratio_windows:
            reasons.append("ads_per_hour_below_baseline")
        if consecutive["low_ads_per_scroll"] >= active_policy.low_ratio_windows:
            reasons.append("ads_per_scroll_below_baseline")
        if (
            target_baseline_ready
            and metrics.target_source == "relevance"
            and _is_valid_relevance_observation_window(metrics, active_policy)
            and _is_low_ratio(
                metrics.target_per_hour,
                active_baseline.target_per_hour,
                active_policy.immediate_drop_ratio,
            )
        ):
            reasons.append("relevant_yield_30pct_drop")
        if (
            target_baseline_ready
            and metrics.target_source == "relevance"
            and consecutive["low_targets_per_hour"] >= active_policy.low_ratio_windows
            and relative_relevance_drop_confident
        ):
            reasons.append("relevant_ads_per_hour_below_baseline")
        elif (
            target_baseline_ready
            and metrics.target_source == "resolved_landings"
            and consecutive["low_targets_per_hour"] >= active_policy.low_ratio_windows
        ):
            observations.append("resolved_landings_per_hour_below_baseline")
        if (
            consecutive["watch_ads_per_hour"] >= active_policy.watch_ratio_windows
            and "ads_per_hour_below_baseline" not in reasons
        ):
            observations.append("ads_per_hour_soft_drop")
        if (
            consecutive["watch_ads_per_scroll"] >= active_policy.watch_ratio_windows
            and "ads_per_scroll_below_baseline" not in reasons
        ):
            observations.append("ads_per_scroll_soft_drop")
        if (
            target_baseline_ready
            and metrics.target_source == "relevance"
            and consecutive["watch_targets_per_hour"]
            >= active_policy.watch_ratio_windows
            and "relevant_ads_per_hour_below_baseline" not in reasons
        ):
            observations.append("relevant_ads_per_hour_soft_drop")
        elif (
            target_baseline_ready
            and metrics.target_source == "resolved_landings"
            and consecutive["watch_targets_per_hour"]
            >= active_policy.watch_ratio_windows
        ):
            observations.append("resolved_landings_per_hour_soft_drop")
        if (
            consecutive["watch_ads_per_hour"]
            >= active_policy.soft_drop_calibration_windows
            and consecutive["watch_ads_per_scroll"]
            >= active_policy.soft_drop_calibration_windows
            and "ads_per_hour_below_baseline" not in reasons
            and "ads_per_scroll_below_baseline" not in reasons
        ):
            reasons.append("ad_yield_sustained_soft_drop")
        if (
            target_baseline_ready
            and metrics.target_source == "relevance"
            and consecutive["watch_targets_per_hour"]
            >= active_policy.soft_drop_calibration_windows
            and soft_relevance_drop_confident
            and "relevant_ads_per_hour_below_baseline" not in reasons
        ):
            reasons.append("relevant_ad_yield_sustained_soft_drop")

        proactive_signals = _proactive_quality_drop_signals(
            metrics,
            active_baseline,
            active_policy,
        )
        observations.extend(proactive_signals)
        if (
            active_policy.proactive_quality_drop_enabled
            and active_baseline.trusted
            and len(proactive_signals)
            >= active_policy.proactive_quality_drop_min_signals
        ):
            reasons.append("proactive_quality_drop")

    if (
        consecutive["low_relevant_rate"] >= active_policy.low_ratio_windows
        and absolute_relevance_drop_confident
    ):
        reasons.append("relevance_rate_too_low")
    if relevance_signal_valid and metrics.relevant_rate is not None:
        relevant_ads = int(metrics.relevant_ads or 0)
        if relevant_ads == 0:
            reasons.append("zero_relevant_ads")
        elif relevant_ads == 1:
            reasons.append("one_relevant_ad")
        elif metrics.relevant_rate < active_policy.minimum_healthy_relevant_rate:
            reasons.append("relevance_rate_below_minimum")
        elif relevant_ads < active_policy.minimum_healthy_relevant_ads:
            reasons.append("too_few_relevant_ads")
    if (
        target_baseline_ready
        and (
            consecutive["low_relevant_rate_vs_baseline"]
            >= active_policy.low_ratio_windows
        )
        and relative_relevance_drop_confident
    ):
        reasons.append("relevance_rate_below_baseline")
    elif target_baseline_ready and (
        consecutive["watch_relevant_rate_vs_baseline"]
        >= active_policy.watch_ratio_windows
    ):
        observations.append("relevance_rate_soft_drop")
    if (
        target_baseline_ready
        and consecutive["watch_relevant_rate_vs_baseline"]
        >= active_policy.soft_drop_calibration_windows
        and soft_relevance_drop_confident
        and "relevance_rate_below_baseline" not in reasons
    ):
        reasons.append("relevance_rate_sustained_soft_drop")

    if not reasons and _maintenance_calibration_due(
        metrics,
        previous,
        last_calibration_at=last_calibration_at,
        now=now_dt,
        policy=active_policy,
    ):
        reasons.append("periodic_account_maintenance")

    cooldown_seconds = active_policy.calibration_cooldown_seconds
    if (
        "zero_ads_repeated" in reasons
        or "zero_relevant_ads" in reasons
        or "one_relevant_ad" in reasons
        or "relevance_rate_below_minimum" in reasons
        or "too_few_relevant_ads" in reasons
    ):
        cooldown_seconds = active_policy.zero_ads_calibration_cooldown_seconds
    elif "periodic_account_maintenance" in reasons:
        cooldown_seconds = active_policy.maintenance_calibration_interval_seconds
    effective_cooldown = _cooldown_active(
        last_calibration_at,
        now_dt,
        active_policy,
        cooldown_seconds=cooldown_seconds,
    )
    if effective_cooldown:
        calibration_blockers.append("calibration_cooldown")
    if (
        not effective_cooldown
        and attempts
        and _retry_cooldown_active(attempts[-1], now_dt, active_policy)
    ):
        calibration_blockers.append("calibration_retry_cooldown")
    if "zero_ads_repeated" in reasons:
        zero_ads_attempts = _attempts_after_last_nonzero_run(attempts, previous)
        if _zero_ads_calibration_backoff_active(
            zero_ads_attempts,
            now_dt,
            active_policy,
        ):
            calibration_blockers.append("zero_ads_calibration_backoff")

    if blockers:
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
                for blocker in blockers
            )
            else "watch"
        )
        return CalibrationDecision(
            status=status,
            should_calibrate=False,
            severity="blocked",
            reasons=reasons,
            blockers=blockers,
            observations=observations,
            consecutive=consecutive,
            baseline=active_baseline,
            metrics=metrics,
        )

    if reasons and calibration_blockers:
        return CalibrationDecision(
            status="watch",
            should_calibrate=False,
            severity="blocked",
            reasons=reasons,
            blockers=calibration_blockers,
            observations=observations,
            consecutive=consecutive,
            baseline=active_baseline,
            metrics=metrics,
        )

    if reasons:
        return CalibrationDecision(
            status="calibrate",
            should_calibrate=True,
            severity=(
                "high"
                if "zero_ads_repeated" in reasons
                else "low"
                if "periodic_account_maintenance" in reasons
                else "medium"
            ),
            reasons=reasons,
            blockers=[],
            observations=observations,
            consecutive=consecutive,
            baseline=active_baseline,
            metrics=metrics,
        )

    status = (
        "watch"
        if observations
        else "healthy"
        if baseline_ready and metrics.ads_total > 0
        else "watch"
    )
    return CalibrationDecision(
        status=status,
        should_calibrate=False,
        severity="ok" if status == "healthy" else "low",
        reasons=[],
        blockers=[],
        observations=observations,
        consecutive=consecutive,
        baseline=active_baseline,
        metrics=metrics,
    )


def metrics_from_dict(raw: dict[str, Any]) -> RunMetrics:
    values: dict[str, Any] = {}
    for item in dataclasses.fields(RunMetrics):
        if item.name in raw:
            values[item.name] = raw[item.name]
        elif item.name == "geo_observed":
            values[item.name] = bool(raw.get("profile_country"))
        elif item.name == "octo_headless":
            values[item.name] = False
        elif item.default is not dataclasses.MISSING:
            values[item.name] = item.default
        elif item.default_factory is not dataclasses.MISSING:
            values[item.name] = item.default_factory()
    return RunMetrics(**values)


def baseline_from_history(
    history: list[RunMetrics],
    *,
    policy: CalibrationPolicy | None = None,
) -> MetricBaseline:
    active_policy = policy or CalibrationPolicy()
    good_runs = [
        metrics
        for metrics in history
        if is_good_baseline_candidate(metrics, active_policy)
    ]
    return MetricBaseline.from_good_runs(
        good_runs,
        max_samples=active_policy.baseline_window,
        min_healthy_relevant_rate=(active_policy.minimum_healthy_relevant_rate),
        min_healthy_relevant_ads=active_policy.minimum_healthy_relevant_ads,
    )


def _is_low_ratio(
    current: float | None,
    baseline: float | None,
    ratio: float,
    min_delta: float = 0.0,
) -> bool:
    if current is None or baseline is None or baseline <= 0:
        return False
    return current < baseline * ratio and baseline - current >= min_delta


def _proactive_quality_drop_signals(
    metrics: RunMetrics,
    baseline: MetricBaseline,
    policy: CalibrationPolicy,
) -> list[str]:
    if (
        not policy.proactive_quality_drop_enabled
        or metrics.target_source != "relevance"
        or not _is_valid_relevance_observation_window(metrics, policy)
        or metrics.relevance_classified_ads
        < policy.proactive_quality_drop_min_classified_ads
        or metrics.relevant_rate is None
        or metrics.relevant_rate < policy.minimum_healthy_relevant_rate
        or int(metrics.relevant_ads or 0) < policy.minimum_healthy_relevant_ads
    ):
        return []

    ratio = policy.proactive_quality_drop_ratio
    comparisons = (
        (
            "proactive_relevance_rate_drop",
            metrics.relevant_rate,
            baseline.relevant_rate,
        ),
        (
            "proactive_relevant_yield_drop",
            metrics.target_per_hour,
            baseline.target_per_hour,
        ),
        (
            "proactive_relevant_scroll_density_drop",
            metrics.target_per_100_scrolls,
            baseline.target_per_100_scrolls,
        ),
    )
    return [
        name
        for name, current, reference in comparisons
        if _is_low_ratio(current, reference, ratio)
    ]


def _is_valid_observation_window(
    metrics: RunMetrics,
    policy: CalibrationPolicy,
) -> bool:
    if metrics.return_code not in {None, 0}:
        return False
    if _is_bad_stop_reason(metrics.stop_reason):
        return False
    if not metrics.geo_match:
        return False
    if not metrics.geo_observed:
        return False
    if (
        metrics.elapsed_seconds is None
        or metrics.elapsed_seconds < policy.min_elapsed_seconds
    ):
        return False
    if metrics.ads_total == 0 and (
        metrics.scrolls is None or metrics.scrolls < policy.min_scrolls
    ):
        return False
    return True


def _is_valid_relevance_observation_window(
    metrics: RunMetrics,
    policy: CalibrationPolicy,
) -> bool:
    if metrics.return_code not in {None, 0}:
        return False
    if _is_bad_stop_reason(metrics.stop_reason) and metrics.stop_reason not in {
        "resolve_timeout",
        "video_timeout",
    }:
        return False
    if not metrics.geo_match or not metrics.geo_observed:
        return False
    if not metrics.relevance_known:
        return False
    if metrics.relevance_classified_ads <= 0:
        return False
    if (
        metrics.relevance_coverage is not None
        and metrics.relevance_coverage < policy.min_relevance_coverage
    ):
        return False
    return True


def _target_baseline_comparison_allowed(
    metrics: RunMetrics,
    policy: CalibrationPolicy,
) -> bool:
    if metrics.target_source != "relevance":
        return True
    return (
        _is_valid_relevance_observation_window(metrics, policy)
        and metrics.relevant_rate is not None
        and metrics.relevant_rate >= policy.minimum_healthy_relevant_rate
        and int(metrics.relevant_ads or 0) >= policy.minimum_healthy_relevant_ads
    )


def _is_bad_stop_reason(value: str | None) -> bool:
    return value in {
        "interrupted",
        "octo_proxy_error",
        "octo_start_error",
        "facebook_login_required",
        "resolve_timeout",
        "scroll_failed",
        "video_timeout",
    }


def _relevance_drop_confident(
    current: RunMetrics,
    previous: list[RunMetrics],
    *,
    threshold: float,
    policy: CalibrationPolicy,
) -> bool:
    runs: list[RunMetrics] = []
    for run in [current, *reversed(previous)]:
        if run is not current and not _same_relevance_observation_series(current, run):
            break
        if not _is_valid_relevance_observation_window(run, policy):
            break
        if run.relevant_rate is None or run.relevant_rate >= threshold:
            break
        runs.append(run)
        classified = sum(item.relevance_classified_ads for item in runs)
        if (
            len(runs) >= policy.low_ratio_windows
            and classified >= policy.min_relevance_classified_total
            and _wilson_upper_bound(
                sum(int(item.relevant_ads or 0) for item in runs),
                classified,
                z=policy.relevance_confidence_z,
            )
            < threshold
        ):
            return True
        if len(runs) >= max(policy.low_ratio_windows, policy.baseline_window):
            break
    return False


def _wilson_upper_bound(successes: int, total: int, *, z: float) -> float:
    if total <= 0:
        return 1.0
    proportion = successes / total
    z_squared = z * z
    denominator = 1 + z_squared / total
    center = proportion + z_squared / (2 * total)
    margin = z * math.sqrt(
        proportion * (1 - proportion) / total + z_squared / (4 * total * total)
    )
    return (center + margin) / denominator


def _window_bucket(elapsed_seconds: float | None) -> float | None:
    if elapsed_seconds is None or elapsed_seconds <= 0:
        return None
    return float(max(300, round(elapsed_seconds / 300) * 300))


def _consecutive_count(
    current: RunMetrics,
    previous: list[RunMetrics],
    predicate,
    *,
    same_series=None,
) -> int:
    series_matcher = same_series or _same_observation_series
    count = 0
    for run in [current, *reversed(previous)]:
        if run is not current and not series_matcher(current, run):
            break
        if not predicate(run):
            break
        count += 1
    return count


def _same_observation_series(current: RunMetrics, previous: RunMetrics) -> bool:
    if _window_bucket(current.elapsed_seconds) != _window_bucket(
        previous.elapsed_seconds
    ):
        return False
    if current.octo_headless != previous.octo_headless:
        return False
    if current.collector_metric_version != previous.collector_metric_version:
        return False
    if current.profile_uuid and previous.profile_uuid:
        return current.profile_uuid == previous.profile_uuid
    return True


def _same_relevance_observation_series(
    current: RunMetrics,
    previous: RunMetrics,
) -> bool:
    if current.octo_headless != previous.octo_headless:
        return False
    if current.collector_metric_version != previous.collector_metric_version:
        return False
    if current.profile_uuid and previous.profile_uuid:
        return current.profile_uuid == previous.profile_uuid
    return True


def _cooldown_active(
    last_calibration_at: str | datetime | None,
    now: datetime,
    policy: CalibrationPolicy,
    *,
    cooldown_seconds: float | None = None,
) -> bool:
    last = _parse_datetime(last_calibration_at)
    if not last:
        return False
    seconds = (
        policy.calibration_cooldown_seconds
        if cooldown_seconds is None
        else cooldown_seconds
    )
    return now - last < timedelta(seconds=seconds)


def _retry_cooldown_active(
    last_attempt_at: str | datetime | None,
    now: datetime,
    policy: CalibrationPolicy,
) -> bool:
    last = _parse_datetime(last_attempt_at)
    if not last:
        return False
    return now - last < timedelta(seconds=policy.calibration_retry_cooldown_seconds)


def _maintenance_calibration_due(
    current: RunMetrics,
    history: list[RunMetrics],
    *,
    last_calibration_at: str | datetime | None,
    now: datetime,
    policy: CalibrationPolicy,
) -> bool:
    interval = policy.maintenance_calibration_interval_seconds
    if interval <= 0 or current.ads_total <= 0:
        return False

    valid_runs: list[RunMetrics] = []
    for run in [current, *reversed(history)]:
        if run is not current and not _same_relevance_observation_series(current, run):
            break
        if not _is_valid_observation_window(
            run, policy
        ) and not _is_valid_relevance_observation_window(run, policy):
            break
        valid_runs.append(run)
    if len(valid_runs) < policy.maintenance_min_valid_windows:
        return False

    last_calibration = _parse_datetime(last_calibration_at)
    if last_calibration is not None:
        return now - last_calibration >= timedelta(seconds=interval)

    first_observation = min(
        (
            timestamp
            for run in valid_runs
            for timestamp in [
                _parse_datetime(run.finished_at),
                _parse_datetime(run.started_at),
            ]
            if timestamp is not None
        ),
        default=None,
    )
    return first_observation is not None and now - first_observation >= timedelta(
        seconds=interval
    )


def _attempts_after_last_nonzero_run(
    attempts: list[str | datetime],
    history: list[RunMetrics],
) -> list[datetime]:
    parsed_attempts = sorted(
        timestamp
        for timestamp in (_parse_datetime(value) for value in attempts)
        if timestamp is not None
    )
    recovered_at = max(
        (
            timestamp
            for run in history
            if run.ads_total > 0
            for timestamp in [_parse_datetime(run.finished_at)]
            if timestamp is not None
        ),
        default=None,
    )
    if recovered_at is None:
        return parsed_attempts
    return [timestamp for timestamp in parsed_attempts if timestamp > recovered_at]


def _zero_ads_calibration_backoff_active(
    attempts: list[datetime],
    now: datetime,
    policy: CalibrationPolicy,
) -> bool:
    limit = policy.zero_ads_calibration_burst_limit
    backoff_seconds = policy.zero_ads_calibration_backoff_seconds
    if limit < 1 or backoff_seconds <= 0:
        return False
    eligible = sorted(timestamp for timestamp in attempts if timestamp <= now)
    if len(eligible) < limit:
        return False

    burst_count = 1
    newer = eligible[-1]
    for older in reversed(eligible[:-1]):
        if newer - older >= timedelta(seconds=backoff_seconds):
            break
        burst_count += 1
        newer = older
    return burst_count >= limit and now - eligible[-1] < timedelta(
        seconds=backoff_seconds
    )


def _daily_limit_reached(
    calibration_timestamps: list[str | datetime],
    now: datetime,
    policy: CalibrationPolicy,
) -> bool:
    since = now - timedelta(hours=24)
    recent = [
        timestamp
        for timestamp in (_parse_datetime(value) for value in calibration_timestamps)
        if timestamp and timestamp >= since
    ]
    return len(recent) >= policy.max_calibrations_per_24h

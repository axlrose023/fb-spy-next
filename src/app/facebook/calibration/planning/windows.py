from __future__ import annotations

import math
from collections.abc import Callable

from app.facebook.profiles import MetricBaseline, window_bucket
from app.facebook.runs import RunMetrics

from ..models import CalibrationPolicy
from .baseline import BAD_STOP_REASONS

MetricPredicate = Callable[[RunMetrics], bool]
SeriesMatcher = Callable[[RunMetrics, RunMetrics], bool]


def is_low_ratio(
    current: float | None,
    baseline: float | None,
    ratio: float,
    min_delta: float = 0.0,
) -> bool:
    if current is None or baseline is None or baseline <= 0:
        return False
    return current < baseline * ratio and baseline - current >= min_delta


def proactive_quality_drop_signals(
    metrics: RunMetrics,
    baseline: MetricBaseline,
    policy: CalibrationPolicy,
) -> list[str]:
    if (
        not policy.proactive_quality_drop_enabled
        or metrics.target_source != "relevance"
        or not is_valid_relevance_window(metrics, policy)
        or metrics.relevance_classified_ads
        < policy.proactive_quality_drop_min_classified_ads
        or metrics.relevant_rate is None
        or metrics.relevant_rate < policy.minimum_healthy_relevant_rate
        or int(metrics.relevant_ads or 0) < policy.minimum_healthy_relevant_ads
    ):
        return []

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
        if is_low_ratio(current, reference, policy.proactive_quality_drop_ratio)
    ]


def is_valid_observation_window(
    metrics: RunMetrics,
    policy: CalibrationPolicy,
) -> bool:
    if metrics.return_code not in {None, 0}:
        return False
    if is_bad_stop_reason(metrics.stop_reason):
        return False
    if not metrics.geo_match or not metrics.geo_observed:
        return False
    if (
        metrics.elapsed_seconds is None
        or metrics.elapsed_seconds < policy.min_elapsed_seconds
    ):
        return False
    return not (
        metrics.ads_total == 0
        and (metrics.scrolls is None or metrics.scrolls < policy.min_scrolls)
    )


def is_valid_relevance_window(
    metrics: RunMetrics,
    policy: CalibrationPolicy,
) -> bool:
    if metrics.return_code not in {None, 0}:
        return False
    if is_bad_stop_reason(metrics.stop_reason) and metrics.stop_reason not in {
        "resolve_timeout",
        "video_timeout",
    }:
        return False
    if not metrics.geo_match or not metrics.geo_observed or not metrics.relevance_known:
        return False
    if metrics.relevance_classified_ads <= 0:
        return False
    return not (
        metrics.relevance_coverage is not None
        and metrics.relevance_coverage < policy.min_relevance_coverage
    )


def target_baseline_comparison_allowed(
    metrics: RunMetrics,
    policy: CalibrationPolicy,
) -> bool:
    if metrics.target_source != "relevance":
        return True
    return (
        is_valid_relevance_window(metrics, policy)
        and metrics.relevant_rate is not None
        and metrics.relevant_rate >= policy.minimum_healthy_relevant_rate
        and int(metrics.relevant_ads or 0) >= policy.minimum_healthy_relevant_ads
    )


def is_bad_stop_reason(value: str | None) -> bool:
    return value in BAD_STOP_REASONS


def relevance_drop_confident(
    current: RunMetrics,
    previous: list[RunMetrics],
    *,
    threshold: float,
    policy: CalibrationPolicy,
) -> bool:
    runs: list[RunMetrics] = []
    for run in [current, *reversed(previous)]:
        if run is not current and not same_relevance_series(current, run):
            break
        if not is_valid_relevance_window(run, policy):
            break
        if run.relevant_rate is None or run.relevant_rate >= threshold:
            break
        runs.append(run)
        classified = sum(item.relevance_classified_ads for item in runs)
        if (
            len(runs) >= policy.low_ratio_windows
            and classified >= policy.min_relevance_classified_total
            and wilson_upper_bound(
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


def wilson_upper_bound(successes: int, total: int, *, z: float) -> float:
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


def consecutive_count(
    current: RunMetrics,
    previous: list[RunMetrics],
    predicate: MetricPredicate,
    *,
    same_series: SeriesMatcher | None = None,
) -> int:
    series_matcher = same_series or same_observation_series
    count = 0
    for run in [current, *reversed(previous)]:
        if run is not current and not series_matcher(current, run):
            break
        if not predicate(run):
            break
        count += 1
    return count


def same_observation_series(current: RunMetrics, previous: RunMetrics) -> bool:
    if window_bucket(current.elapsed_seconds) != window_bucket(
        previous.elapsed_seconds
    ):
        return False
    return same_relevance_series(current, previous)


def same_relevance_series(current: RunMetrics, previous: RunMetrics) -> bool:
    if current.octo_headless != previous.octo_headless:
        return False
    if current.collector_metric_version != previous.collector_metric_version:
        return False
    if current.profile_uuid and previous.profile_uuid:
        return bool(current.profile_uuid == previous.profile_uuid)
    return True

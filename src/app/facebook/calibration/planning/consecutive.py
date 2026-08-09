from __future__ import annotations

from app.facebook.profiles import MetricBaseline
from app.facebook.runs import RunMetrics

from ..models import CalibrationPolicy
from .windows import (
    consecutive_count,
    is_low_ratio,
    is_valid_observation_window,
    is_valid_relevance_window,
    same_relevance_series,
    target_baseline_comparison_allowed,
)


def consecutive_signals(
    metrics: RunMetrics,
    history: list[RunMetrics],
    baseline: MetricBaseline,
    policy: CalibrationPolicy,
) -> dict[str, int]:
    return {
        "zero_ads": consecutive_count(
            metrics,
            history,
            lambda run: is_valid_observation_window(run, policy) and run.ads_total == 0,
        ),
        "absolute_low_ads": consecutive_count(
            metrics,
            history,
            lambda run: (
                is_valid_observation_window(run, policy)
                and run.ads_per_hour is not None
                and run.ads_per_hour <= policy.absolute_low_ads_per_hour
            ),
        ),
        "low_ads_per_hour": consecutive_count(
            metrics,
            history,
            lambda run: (
                is_low_ratio(
                    run.ads_per_hour,
                    baseline.ads_per_hour,
                    policy.low_ads_per_hour_ratio,
                    policy.min_ads_per_hour_drop,
                )
                and is_valid_observation_window(run, policy)
            ),
        ),
        "watch_ads_per_hour": consecutive_count(
            metrics,
            history,
            lambda run: (
                is_low_ratio(
                    run.ads_per_hour,
                    baseline.ads_per_hour,
                    policy.watch_drop_ratio,
                )
                and is_valid_observation_window(run, policy)
            ),
        ),
        "low_targets_per_hour": consecutive_count(
            metrics,
            history,
            lambda run: (
                is_low_ratio(
                    run.target_per_hour,
                    baseline.target_per_hour,
                    policy.low_target_per_hour_ratio,
                    policy.min_target_per_hour_drop,
                )
                and is_valid_observation_window(run, policy)
                and target_baseline_comparison_allowed(run, policy)
            ),
        ),
        "watch_targets_per_hour": consecutive_count(
            metrics,
            history,
            lambda run: (
                is_low_ratio(
                    run.target_per_hour,
                    baseline.target_per_hour,
                    policy.watch_drop_ratio,
                )
                and is_valid_observation_window(run, policy)
                and target_baseline_comparison_allowed(run, policy)
            ),
        ),
        "low_ads_per_scroll": consecutive_count(
            metrics,
            history,
            lambda run: (
                is_low_ratio(
                    run.ads_per_100_scrolls,
                    baseline.ads_per_100_scrolls,
                    policy.low_scroll_density_ratio,
                    policy.min_ads_per_100_scrolls_drop,
                )
                and is_valid_observation_window(run, policy)
            ),
        ),
        "watch_ads_per_scroll": consecutive_count(
            metrics,
            history,
            lambda run: (
                is_low_ratio(
                    run.ads_per_100_scrolls,
                    baseline.ads_per_100_scrolls,
                    policy.watch_drop_ratio,
                )
                and is_valid_observation_window(run, policy)
            ),
        ),
        "low_relevant_rate": consecutive_count(
            metrics,
            history,
            lambda run: (
                is_valid_relevance_window(run, policy)
                and run.relevance_known
                and run.relevant_rate is not None
                and run.relevant_rate < policy.absolute_low_relevant_rate
            ),
            same_series=same_relevance_series,
        ),
        "low_relevant_rate_vs_baseline": consecutive_count(
            metrics,
            history,
            lambda run: (
                is_valid_relevance_window(run, policy)
                and run.relevance_known
                and target_baseline_comparison_allowed(run, policy)
                and is_low_ratio(
                    run.relevant_rate,
                    baseline.relevant_rate,
                    policy.low_target_per_hour_ratio,
                    policy.min_relevant_rate_drop,
                )
            ),
            same_series=same_relevance_series,
        ),
        "watch_relevant_rate_vs_baseline": consecutive_count(
            metrics,
            history,
            lambda run: (
                is_valid_relevance_window(run, policy)
                and run.relevance_known
                and target_baseline_comparison_allowed(run, policy)
                and is_low_ratio(
                    run.relevant_rate,
                    baseline.relevant_rate,
                    policy.watch_drop_ratio,
                )
            ),
            same_series=same_relevance_series,
        ),
    }

from __future__ import annotations

from .context import PlanningContext
from .windows import (
    is_low_ratio,
    is_valid_observation_window,
    is_valid_relevance_window,
    proactive_quality_drop_signals,
)


def collect_calibration_signals(context: PlanningContext) -> None:
    metrics = context.metrics
    policy = context.policy
    consecutive = context.consecutive
    reasons = context.reasons
    observations = context.observations

    if consecutive["zero_ads"] >= policy.zero_ads_windows:
        reasons.append("zero_ads_repeated")
    if (
        "zero_ads_repeated" not in reasons
        and consecutive["absolute_low_ads"] >= policy.absolute_low_ads_windows
    ):
        reasons.append("absolute_low_ad_yield")

    if context.baseline_ready:
        _collect_baseline_signals(context)

    if (
        consecutive["low_relevant_rate"] >= policy.low_ratio_windows
        and context.absolute_relevance_drop_confident
    ):
        reasons.append("relevance_rate_too_low")
    if context.relevance_signal_valid and metrics.relevant_rate is not None:
        relevant_ads = int(metrics.relevant_ads or 0)
        if relevant_ads == 0:
            reasons.append("zero_relevant_ads")
        elif relevant_ads == 1:
            reasons.append("one_relevant_ad")
        elif metrics.relevant_rate < policy.minimum_healthy_relevant_rate:
            reasons.append("relevance_rate_below_minimum")
        elif relevant_ads < policy.minimum_healthy_relevant_ads:
            reasons.append("too_few_relevant_ads")
    if (
        context.target_baseline_ready
        and consecutive["low_relevant_rate_vs_baseline"] >= policy.low_ratio_windows
        and context.relative_relevance_drop_confident
    ):
        reasons.append("relevance_rate_below_baseline")
    elif context.target_baseline_ready and (
        consecutive["watch_relevant_rate_vs_baseline"] >= policy.watch_ratio_windows
    ):
        observations.append("relevance_rate_soft_drop")
    if (
        context.target_baseline_ready
        and consecutive["watch_relevant_rate_vs_baseline"]
        >= policy.soft_drop_calibration_windows
        and context.soft_relevance_drop_confident
        and "relevance_rate_below_baseline" not in reasons
    ):
        reasons.append("relevance_rate_sustained_soft_drop")


def _collect_baseline_signals(context: PlanningContext) -> None:
    metrics = context.metrics
    baseline = context.baseline
    policy = context.policy
    consecutive = context.consecutive
    reasons = context.reasons
    observations = context.observations

    if (
        is_valid_observation_window(metrics, policy)
        and metrics.ads_total > 0
        and is_low_ratio(
            metrics.ads_per_hour,
            baseline.ads_per_hour,
            policy.immediate_drop_ratio,
        )
    ):
        reasons.append("ad_yield_30pct_drop")
    if consecutive["low_ads_per_hour"] >= policy.low_ratio_windows:
        reasons.append("ads_per_hour_below_baseline")
    if consecutive["low_ads_per_scroll"] >= policy.low_ratio_windows:
        reasons.append("ads_per_scroll_below_baseline")
    if (
        context.target_baseline_ready
        and metrics.target_source == "relevance"
        and is_valid_relevance_window(metrics, policy)
        and is_low_ratio(
            metrics.target_per_hour,
            baseline.target_per_hour,
            policy.immediate_drop_ratio,
        )
    ):
        reasons.append("relevant_yield_30pct_drop")
    if (
        context.target_baseline_ready
        and metrics.target_source == "relevance"
        and consecutive["low_targets_per_hour"] >= policy.low_ratio_windows
        and context.relative_relevance_drop_confident
    ):
        reasons.append("relevant_ads_per_hour_below_baseline")
    elif (
        context.target_baseline_ready
        and metrics.target_source == "resolved_landings"
        and consecutive["low_targets_per_hour"] >= policy.low_ratio_windows
    ):
        observations.append("resolved_landings_per_hour_below_baseline")
    if (
        consecutive["watch_ads_per_hour"] >= policy.watch_ratio_windows
        and "ads_per_hour_below_baseline" not in reasons
    ):
        observations.append("ads_per_hour_soft_drop")
    if (
        consecutive["watch_ads_per_scroll"] >= policy.watch_ratio_windows
        and "ads_per_scroll_below_baseline" not in reasons
    ):
        observations.append("ads_per_scroll_soft_drop")
    if (
        context.target_baseline_ready
        and metrics.target_source == "relevance"
        and consecutive["watch_targets_per_hour"] >= policy.watch_ratio_windows
        and "relevant_ads_per_hour_below_baseline" not in reasons
    ):
        observations.append("relevant_ads_per_hour_soft_drop")
    elif (
        context.target_baseline_ready
        and metrics.target_source == "resolved_landings"
        and consecutive["watch_targets_per_hour"] >= policy.watch_ratio_windows
    ):
        observations.append("resolved_landings_per_hour_soft_drop")
    if (
        consecutive["watch_ads_per_hour"] >= policy.soft_drop_calibration_windows
        and consecutive["watch_ads_per_scroll"] >= policy.soft_drop_calibration_windows
        and "ads_per_hour_below_baseline" not in reasons
        and "ads_per_scroll_below_baseline" not in reasons
    ):
        reasons.append("ad_yield_sustained_soft_drop")
    if (
        context.target_baseline_ready
        and metrics.target_source == "relevance"
        and consecutive["watch_targets_per_hour"]
        >= policy.soft_drop_calibration_windows
        and context.soft_relevance_drop_confident
        and "relevant_ads_per_hour_below_baseline" not in reasons
    ):
        reasons.append("relevant_ad_yield_sustained_soft_drop")

    proactive_signals = proactive_quality_drop_signals(metrics, baseline, policy)
    observations.extend(proactive_signals)
    if (
        policy.proactive_quality_drop_enabled
        and baseline.trusted
        and len(proactive_signals) >= policy.proactive_quality_drop_min_signals
    ):
        reasons.append("proactive_quality_drop")

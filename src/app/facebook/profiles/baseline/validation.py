from __future__ import annotations

from app.facebook.runs import RunMetrics

from .models import BaselineRequirements


def is_baseline_candidate(
    metrics: RunMetrics,
    requirements: BaselineRequirements,
) -> bool:
    if metrics.return_code not in {None, 0}:
        return False
    if metrics.stop_reason in requirements.blocked_stop_reasons:
        return False
    if not metrics.geo_observed or not metrics.geo_match:
        return False
    if (
        metrics.elapsed_seconds is None
        or metrics.elapsed_seconds < requirements.min_elapsed_seconds
    ):
        return False
    if metrics.ads_total < requirements.min_ads:
        return False
    if metrics.target_ads < requirements.min_targets:
        return False
    return metrics.ads_per_hour is not None and metrics.ads_per_hour > 0


def window_bucket(elapsed_seconds: float | None) -> float | None:
    if elapsed_seconds is None or elapsed_seconds <= 0:
        return None
    return float(max(300, round(elapsed_seconds / 300) * 300))

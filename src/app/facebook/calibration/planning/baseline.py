from __future__ import annotations

import dataclasses
from typing import Any

from app.facebook.profiles import (
    BaselineBuildOptions,
    BaselineRequirements,
    MetricBaseline,
    build_metric_baseline,
    is_baseline_candidate,
)
from app.facebook.runs import RunMetrics

from ..models import CalibrationPolicy

BAD_STOP_REASONS = frozenset(
    {
        "interrupted",
        "octo_proxy_error",
        "octo_start_error",
        "facebook_login_required",
        "resolve_timeout",
        "scroll_failed",
        "video_timeout",
    }
)


def is_good_baseline_candidate(
    metrics: RunMetrics,
    policy: CalibrationPolicy | None = None,
) -> bool:
    active_policy = policy or CalibrationPolicy()
    return bool(
        is_baseline_candidate(
            metrics,
            BaselineRequirements(
                min_elapsed_seconds=active_policy.min_elapsed_seconds,
                min_ads=active_policy.min_good_ads_for_baseline,
                min_targets=active_policy.min_good_targets_for_baseline,
                blocked_stop_reasons=BAD_STOP_REASONS,
            ),
        )
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
    return build_metric_baseline(
        good_runs,
        BaselineBuildOptions(
            max_samples=active_policy.baseline_window,
            min_healthy_relevant_rate=active_policy.minimum_healthy_relevant_rate,
            min_healthy_relevant_ads=active_policy.minimum_healthy_relevant_ads,
        ),
    )

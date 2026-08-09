from __future__ import annotations

from dataclasses import replace
from typing import Any

from app.facebook.calibration import (
    CalibrationPolicy,
    is_good_baseline_candidate,
    metrics_from_dict,
)
from app.facebook.profiles import (
    BaselineBuildOptions,
    MetricBaseline,
    build_metric_baseline,
)
from app.facebook.runs import RunMetrics


def is_healthy_relevance_result(
    metrics: RunMetrics,
    policy: CalibrationPolicy,
) -> bool:
    return bool(
        metrics.target_source == "relevance"
        and metrics.relevance_known
        and metrics.relevance_coverage is not None
        and metrics.relevance_coverage >= policy.min_relevance_coverage
        and metrics.relevant_rate is not None
        and metrics.relevant_rate >= policy.minimum_healthy_relevant_rate
        and int(metrics.relevant_ads or 0) >= policy.minimum_healthy_relevant_ads
    )


def baseline_from_run_records(
    records: list[dict[str, Any]],
    policy: CalibrationPolicy,
) -> MetricBaseline:
    by_run_dir: dict[str, RunMetrics] = {}
    for item in records:
        raw_metrics = item.get("metrics")
        if not isinstance(raw_metrics, dict):
            continue
        metrics = metrics_from_dict(raw_metrics)
        explicitly_eligible = item.get("seed_baseline") or item.get(
            "baseline_candidate"
        )
        legacy_record = "baseline_candidate" not in item
        if not explicitly_eligible and not (
            legacy_record and is_good_baseline_candidate(metrics, policy)
        ):
            continue
        by_run_dir.pop(metrics.run_dir, None)
        by_run_dir[metrics.run_dir] = metrics
    baseline = build_metric_baseline(
        list(by_run_dir.values()),
        BaselineBuildOptions(
            max_samples=policy.baseline_window,
            min_healthy_relevant_rate=policy.minimum_healthy_relevant_rate,
            min_healthy_relevant_ads=policy.minimum_healthy_relevant_ads,
        ),
    )
    trusted_dirs = {
        str(item.get("run_dir") or "")
        for item in records
        if item.get("seed_baseline") or item.get("trusted_baseline")
    }
    trusted = bool(trusted_dirs.intersection(baseline.source_run_dirs))
    return replace(baseline, trusted=trusted)


def calibration_was_effective(raw: dict[str, Any]) -> bool:
    if "effective" in raw:
        return bool(raw.get("effective"))
    raw_summary = raw.get("summary")
    summary: dict[str, Any] = raw_summary if isinstance(raw_summary, dict) else {}
    return (
        raw.get("return_code") == 0
        and summary.get("status") == "completed"
        and int(summary.get("ok") or 0)
        >= CalibrationPolicy().min_successful_calibration_targets
        and summary.get("interaction_goal_met") is True
    )

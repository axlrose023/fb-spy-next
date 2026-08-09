from __future__ import annotations

import statistics

from app.facebook.runs import RunMetrics

from .models import BaselineBuildOptions, MetricBaseline
from .validation import window_bucket


def build_metric_baseline(
    runs: list[RunMetrics],
    options: BaselineBuildOptions | None = None,
) -> MetricBaseline:
    if not runs:
        return MetricBaseline()
    active = options or BaselineBuildOptions()
    latest_window = window_bucket(runs[-1].elapsed_seconds)
    latest_headless = runs[-1].octo_headless
    latest_metric_version = runs[-1].collector_metric_version
    comparable = [
        run
        for run in runs
        if window_bucket(run.elapsed_seconds) == latest_window
        and run.octo_headless == latest_headless
        and run.collector_metric_version == latest_metric_version
    ]
    samples = comparable[-max(1, active.max_samples) :]
    relevance_samples = [
        run
        for run in samples
        if run.target_source == "relevance"
        and run.relevance_known
        and run.relevant_rate is not None
        and run.relevant_rate >= active.min_healthy_relevant_rate
        and int(run.relevant_ads or 0) >= active.min_healthy_relevant_ads
    ]
    target_samples = relevance_samples or [
        run for run in samples if run.target_source == "resolved_landings"
    ]
    target_source = target_samples[-1].target_source if target_samples else None

    return MetricBaseline(
        sample_count=len(samples),
        collector_metric_version=latest_metric_version,
        source_run_dirs=[run.run_dir for run in samples],
        window_seconds=latest_window,
        octo_headless=latest_headless,
        target_source=target_source,
        target_sample_count=len(target_samples),
        ads_per_hour=_median([run.ads_per_hour for run in samples]),
        target_per_hour=_median([run.target_per_hour for run in target_samples]),
        resolved_per_hour=_median([run.resolved_per_hour for run in samples]),
        ads_per_100_scrolls=_median([run.ads_per_100_scrolls for run in samples]),
        target_per_100_scrolls=_median(
            [run.target_per_100_scrolls for run in target_samples]
        ),
        resolved_per_100_scrolls=_median(
            [run.resolved_per_100_scrolls for run in samples]
        ),
        relevant_rate=_median([run.relevant_rate for run in relevance_samples]),
        landing_resolution_rate=_median(
            [_safe_div(run.resolved_landings, run.link_ads) for run in samples]
        ),
        domain_diversity_rate=_median(
            [_safe_div(run.unique_domains, run.ads_total) for run in samples]
        ),
    )


def _median(values: list[float | None]) -> float | None:
    cleaned = [value for value in values if value is not None]
    return float(statistics.median(cleaned)) if cleaned else None


def _safe_div(
    numerator: float | int | None,
    denominator: float | int | None,
) -> float | None:
    if numerator is None or denominator is None or denominator == 0:
        return None
    return float(numerator) / float(denominator)

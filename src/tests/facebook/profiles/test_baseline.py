from __future__ import annotations

import pytest

from app.facebook.profiles import (
    BaselineBuildOptions,
    BaselineRequirements,
    MetricBaseline,
    build_metric_baseline,
    is_baseline_candidate,
    window_bucket,
)
from app.facebook.runs import RunMetrics

pytestmark = pytest.mark.unit


def metrics(run_dir: str, **overrides: object) -> RunMetrics:
    values: dict[str, object] = {
        "run_dir": run_dir,
        "profile_uuid": "profile",
        "profile_country": "Spain",
        "geo_observed": True,
        "geo_match": True,
        "elapsed_seconds": 900,
        "ads_total": 30,
        "target_ads": 10,
        "ads_per_hour": 120,
        "target_source": "relevance",
        "relevance_known": True,
        "relevant_ads": 10,
        "relevant_rate": 0.8,
        "target_per_hour": 40,
        "resolved_landings": 10,
        "link_ads": 20,
        "unique_domains": 6,
    }
    values.update(overrides)
    return RunMetrics(**values)  # type: ignore[arg-type]


def test_baseline_builder_keeps_latest_comparable_series_and_medians() -> None:
    baseline = build_metric_baseline(
        [
            metrics("short", elapsed_seconds=300, ads_per_hour=999),
            metrics("first", ads_per_hour=100, target_per_hour=30),
            metrics("second", ads_per_hour=140, target_per_hour=50),
        ],
        BaselineBuildOptions(
            max_samples=2,
            min_healthy_relevant_rate=0.75,
            min_healthy_relevant_ads=5,
        ),
    )

    assert baseline.sample_count == 2
    assert baseline.source_run_dirs == ["first", "second"]
    assert baseline.ads_per_hour == 120
    assert baseline.target_per_hour == 40
    assert baseline.relevant_rate == 0.8
    assert baseline.landing_resolution_rate == 0.5
    assert baseline.domain_diversity_rate == 0.2
    assert MetricBaseline.from_dict(baseline.to_dict()) == baseline


def test_baseline_validation_rejects_infrastructure_and_bad_observation() -> None:
    requirements = BaselineRequirements(
        min_elapsed_seconds=600,
        min_ads=10,
        min_targets=5,
        blocked_stop_reasons=frozenset({"octo_start_error"}),
    )

    assert is_baseline_candidate(metrics("healthy"), requirements) is True
    assert (
        is_baseline_candidate(
            metrics("octo", stop_reason="octo_start_error"),
            requirements,
        )
        is False
    )
    assert (
        is_baseline_candidate(metrics("geo", geo_observed=False), requirements) is False
    )
    assert is_baseline_candidate(metrics("zero", ads_per_hour=0), requirements) is False
    assert window_bucket(None) is None
    assert window_bucket(1) == 300
    assert window_bucket(740) == 600

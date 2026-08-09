from __future__ import annotations

import dataclasses
from dataclasses import asdict, dataclass, field
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from app.facebook.runs import RunMetrics


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
        from .builder import build_metric_baseline

        return build_metric_baseline(
            runs,
            BaselineBuildOptions(
                max_samples=max_samples,
                min_healthy_relevant_rate=min_healthy_relevant_rate,
                min_healthy_relevant_ads=min_healthy_relevant_ads,
            ),
        )


@dataclass(frozen=True, slots=True)
class BaselineBuildOptions:
    max_samples: int = 8
    min_healthy_relevant_rate: float = 0.0
    min_healthy_relevant_ads: int = 0


@dataclass(frozen=True, slots=True)
class BaselineRequirements:
    min_elapsed_seconds: float
    min_ads: int
    min_targets: int
    blocked_stop_reasons: frozenset[str]

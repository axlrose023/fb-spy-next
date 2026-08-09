from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any

from app.facebook.profiles import MetricBaseline
from app.facebook.runs import RunMetrics


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


@dataclass(frozen=True)
class CalibrationPlan:
    tier: str
    target_limit: int
    target_goal: int
    max_reactions: int
    max_follows: int
    max_comments: int
    min_interactions: int


@dataclass(frozen=True, slots=True)
class CalibrationLoopPolicy:
    session_seconds: float = 0.0
    repeat_targets_until_deadline: bool = False
    pause_between_targets: float = 0.0
    min_successful_targets: int = 0
    min_interactions: int = 1
    comment_every: int = 0
    max_comments: int = 0
    continue_on_target_navigation_error: bool = False

    @property
    def has_deadline(self) -> bool:
        return self.session_seconds > 0

    @property
    def repeats_targets(self) -> bool:
        return self.repeat_targets_until_deadline and self.has_deadline


@dataclass(frozen=True, slots=True)
class CalibrationRunResult:
    results: tuple[dict[str, Any], ...]
    interactions: dict[str, int]
    target_goal_met: bool
    interaction_goal_met: bool
    infrastructure_error: str | None
    termination: str

    @property
    def ok(self) -> int:
        return sum(1 for result in self.results if result.get("ok"))

    @property
    def failed(self) -> int:
        return len(self.results) - self.ok

    @property
    def successful(self) -> bool:
        return (
            self.infrastructure_error is None
            and self.target_goal_met
            and self.interaction_goal_met
        )

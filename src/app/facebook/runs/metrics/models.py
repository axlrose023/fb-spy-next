from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any


@dataclass(frozen=True)
class RunMetrics:
    run_dir: str
    collector_metric_version: int = 1
    profile_uuid: str | None = None
    profile_country: str | None = None
    expected_country: str | None = None
    octo_ip: str | None = None
    octo_headless: bool | None = None
    started_at: str | None = None
    finished_at: str | None = None
    return_code: int | None = None
    stop_reason: str | None = None
    elapsed_seconds: float | None = None
    requested_minutes: float | None = None
    scrolls: int | None = None
    refreshes: int | None = None
    captured_candidates: int | None = None
    duplicate_fb_ad_ids: int = 0
    ads_total: int = 0
    link_ads: int = 0
    video_ads: int = 0
    in_facebook_ads: int = 0
    resolved_landings: int = 0
    unique_landing_clean: int = 0
    unique_fb_ad_ids: int = 0
    unique_advertisers: int = 0
    unique_domains: int = 0
    top_domain_share: float | None = None
    screenshot_attempted: int = 0
    screenshot_ok: int = 0
    screenshot_ok_rate: float | None = None
    country_match_rate: float | None = None
    geo_observed: bool = False
    geo_match: bool = True
    relevance_known: bool = False
    relevance_classified_ads: int = 0
    relevance_coverage: float | None = None
    relevant_ads: int | None = None
    relevant_rate: float | None = None
    target_source: str = "resolved_landings"
    target_ads: int = 0
    ads_per_hour: float | None = None
    target_per_hour: float | None = None
    resolved_per_hour: float | None = None
    ads_per_100_scrolls: float | None = None
    target_per_100_scrolls: float | None = None
    resolved_per_100_scrolls: float | None = None
    calibration_targets_available: int | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

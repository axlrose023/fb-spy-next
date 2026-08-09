from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, cast

from ...models import CollectedAd
from ...service import CollectionService
from .debug_recorder import DebugRecorder
from .feed_reader import FeedReader


@dataclass(frozen=True, slots=True)
class CollectionOptions:
    run_dir: Path
    minutes: float
    max_scrolls: int
    screenshots: bool
    resolve_landings: bool
    resolve_max: int
    scroll_px: int
    debug: DebugRecorder | None
    feed_url: str
    country: str | None
    archive_landings: bool
    landing_archive_timeout: float
    landing_archive_max_resources: int
    record_videos: bool
    video_max_seconds: float
    video_fps: int
    max_ads_per_view: int
    resolve_post_urls: bool
    interest_safe_mode: bool
    interest_safe_overrides: tuple[str, ...]

    @property
    def screenshots_dir(self) -> Path:
        return self.run_dir / "screens"

    @property
    def videos_dir(self) -> Path:
        return self.run_dir / "videos"


@dataclass(slots=True)
class CollectionRunState:
    options: CollectionOptions
    service: CollectionService
    feed_reader: FeedReader
    started_at: str
    started_clock: float
    deadline: float
    next_long_pause_scroll: int
    resolved: int = 0
    captured: int = 0
    duplicate_fb_ad_ids: int = 0
    resolve_timeouts: int = 0
    video_timeouts: int = 0
    cta_click_attempts: int = 0
    video_play_attempts: int = 0
    comment_open_attempts: int = 0
    scrolls: int = 0
    refreshes: int = 0
    last_ad_scroll: int = 0
    interrupted: bool = False
    stop_reason: str = ""
    facebook_login_required: bool = False
    passive_guard_installed: bool = False
    passive_pre_navigation_guard: dict[str, Any] = field(default_factory=dict)

    @property
    def ads(self) -> dict[str, CollectedAd]:
        return cast(dict[str, CollectedAd], self.service.registry.ads)

    def remaining_seconds(self, now: float) -> float:
        return self.deadline - now

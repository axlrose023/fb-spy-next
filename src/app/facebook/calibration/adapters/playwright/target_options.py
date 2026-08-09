from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class CalibrationBrowserOptions:
    timeout_ms: int
    locate_timeout_ms: int
    wait_after_load: float
    screenshots: bool
    view_seconds: float
    interaction_dry_run: bool
    comment_templates: tuple[str, ...]
    visit_landing: bool
    landing_view_seconds: float
    landing_timeout_ms: int

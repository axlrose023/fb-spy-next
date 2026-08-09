from __future__ import annotations

import re
import time
from typing import Any

from app.browser import (
    BrowserOperationDeadlineExceeded,
    hard_deadline,
)
from app.facebook.enrichment import record_ad_video

from ...models import CollectedAd
from .screenshot import (
    has_video_creative,
    save_ad_screenshot,
    screenshot_has_blank_media,
)
from .state import CollectionRunState


def save_candidate_screenshot(
    page: Any,
    row: dict[str, Any],
    state: CollectionRunState,
    ad: CollectedAd,
    *,
    debug_id: int,
    creative_area: int,
) -> None:
    options = state.options
    if not options.screenshots or state.remaining_seconds(time.time()) <= 8:
        return
    filename = options.screenshots_dir / screenshot_filename(debug_id, ad)
    expect_media = bool(row.get("has_video")) or creative_area >= 45000
    exact = save_ad_screenshot(
        page,
        filename,
        row.get("element_id"),
        expect_media=expect_media,
        interest_safe=options.interest_safe_mode,
    )
    if filename.exists():
        ad.screenshot = str(filename.relative_to(options.run_dir))
        if not exact:
            ad.screenshot_ok = False
            ad.screenshot_issue = "viewport_fallback"
        elif expect_media and screenshot_has_blank_media(filename):
            ad.screenshot_ok = False
            ad.screenshot_issue = "blank_media"
    if row.get("element_id"):
        ad.has_video = ad.has_video or has_video_creative(page, row.get("element_id"))
        if ad.has_video and ad.ad_type == "in_facebook":
            ad.ad_type = "video"


def record_candidate_video(
    page: Any,
    row: dict[str, Any],
    state: CollectionRunState,
    ad: CollectedAd,
    *,
    debug_id: int,
) -> bool:
    options = state.options
    if (
        not options.record_videos
        or not ad.has_video
        or not row.get("element_id")
        or ad.video
    ):
        return True
    budget = min(float(options.video_max_seconds or 0), 45.0) + 20.0
    if state.remaining_seconds(time.time()) <= budget:
        report_video_failure(state, ad, debug_id=debug_id, issue="time_budget")
        return True

    filename = options.videos_dir / video_filename(debug_id, ad)
    print(f"  recording video {filename.name}", flush=True)
    state.video_play_attempts += 1
    try:
        with hard_deadline(
            budget,
            f"video capture: {ad.displayed_domain or ad.advertiser}",
        ):
            ok, issue = record_ad_video(
                page,
                filename,
                row.get("element_id"),
                max_seconds=options.video_max_seconds,
                fps=options.video_fps,
                debug=options.debug,
                debug_id=debug_id,
            )
    except BrowserOperationDeadlineExceeded as exc:
        state.video_timeouts += 1
        state.stop_reason = "video_timeout"
        print(
            f"  video timeout {ad.displayed_domain or ad.advertiser} after "
            f"{budget:.0f}s; ending this cycle with the captured ad saved",
            flush=True,
        )
        if options.debug:
            options.debug.event(
                "video_hard_timeout",
                debug_id=debug_id,
                domain=ad.displayed_domain,
                timeout_seconds=budget,
                error=str(exc),
            )
        return False
    if ok:
        ad.video = str(filename.relative_to(options.run_dir))
        print(f"  recorded video {filename.name}", flush=True)
    else:
        report_video_failure(state, ad, debug_id=debug_id, issue=issue)
    return True


def report_video_failure(
    state: CollectionRunState,
    ad: CollectedAd,
    *,
    debug_id: int,
    issue: str,
) -> None:
    print(
        f"  video record skipped {ad.displayed_domain or ad.advertiser}: {issue}",
        flush=True,
    )
    if state.options.debug:
        state.options.debug.event(
            "video_record_failed",
            debug_id=debug_id,
            advertiser=ad.advertiser,
            domain=ad.displayed_domain,
            issue=issue,
        )


def screenshot_filename(debug_id: int, ad: CollectedAd) -> str:
    return (
        f"{debug_id:04d}_{slug(ad.displayed_domain or ad.advertiser or 'ad', 24)}.png"
    )


def video_filename(debug_id: int, ad: CollectedAd) -> str:
    return f"{debug_id:04d}_{slug(ad.displayed_domain or ad.advertiser or 'video', 24)}.mp4"


def slug(value: str, limit: int) -> str:
    return re.sub(r"[^a-z0-9]+", "_", value.lower())[:limit]

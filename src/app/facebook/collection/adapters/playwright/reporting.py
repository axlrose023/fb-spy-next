from __future__ import annotations

import time
from typing import Any

from ...artifacts import write_ads, write_json_atomic
from ...models import CollectedAd, utc_now
from ...summary import ad_summary
from .passive_media import passive_media_guard_stats
from .state import CollectionRunState


def finalize_collection(
    page: Any,
    state: CollectionRunState,
    *,
    stop_requested: bool,
) -> dict[str, CollectedAd]:
    options = state.options
    elapsed_seconds = round(time.time() - state.started_clock, 3)
    if not state.stop_reason:
        if state.interrupted or stop_requested:
            state.stop_reason = "interrupted"
        elif state.scrolls >= options.max_scrolls:
            state.stop_reason = "scroll_budget"
        elif elapsed_seconds >= options.minutes * 60:
            state.stop_reason = "time_budget"
        else:
            state.stop_reason = "completed"

    passive_stats = (
        passive_media_guard_stats(page)
        if options.interest_safe_mode
        else {
            "installed": False,
            "blocked_play_calls": 0,
            "pause_events": 0,
            "observed_videos": 0,
        }
    )
    passive_stats.update(state.passive_pre_navigation_guard)
    passive_stats["installed"] = bool(
        passive_stats["installed"] or state.passive_guard_installed
    )
    write_json_atomic(
        options.run_dir / "summary.json",
        {
            "mode": "collect",
            "started_at": state.started_at,
            "finished_at": utc_now(),
            "requested_minutes": options.minutes,
            "elapsed_seconds": elapsed_seconds,
            "max_scrolls": options.max_scrolls,
            "scrolls": state.scrolls,
            "refreshes": state.refreshes,
            "resolve_enabled": options.resolve_landings,
            "resolve_max": options.resolve_max,
            "scroll_px": options.scroll_px,
            "max_ads_per_view": options.max_ads_per_view,
            "feed_url": options.feed_url,
            "stop_reason": state.stop_reason,
            "facebook_login_required": state.facebook_login_required,
            "captured_candidates": state.captured,
            "duplicate_fb_ad_ids": state.duplicate_fb_ad_ids,
            "resolve_timeouts": state.resolve_timeouts,
            "video_timeouts": state.video_timeouts,
            "interest_safe_mode": options.interest_safe_mode,
            "interest_safe_overrides": list(options.interest_safe_overrides),
            "active_actions": {
                "cta_click_attempts": state.cta_click_attempts,
                "video_play_attempts": state.video_play_attempts,
                "comment_open_attempts": state.comment_open_attempts,
            },
            "passive_media_guard": passive_stats,
            **ad_summary(state.ads),
        },
    )
    print(
        f"[collect done] {len(state.ads)} unique ads, {state.resolved} resolved, "
        f"{state.scrolls} scrolls, {state.refreshes} refreshes"
    )
    if options.debug:
        options.debug.event(
            "collect_finished",
            unique_ads=len(state.ads),
            resolved=state.resolved,
            scrolls=state.scrolls,
            refreshes=state.refreshes,
        )
        write_ads(options.run_dir / "ads.partial.json", state.ads)
    return state.ads

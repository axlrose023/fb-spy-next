from __future__ import annotations

import os
import random
import time
import traceback
from collections.abc import Callable
from pathlib import Path
from typing import Any, cast

from app.facebook.feed import install_passive_media_guard, prepare_passive_media_guard
from app.facebook.navigation import facebook_login_required, goto_with_retry
from app.facebook.timing import utc_now

from ...artifacts import ArtifactPolicy, write_ads
from ...models import CollectedAd
from ...service import CollectionService
from ...stop import stop_requested as global_stop_requested
from .candidate import process_candidate
from .debug_recorder import DebugRecorder
from .feed_reader import FeedReader
from .reporting import finalize_collection
from .scrolling import advance_feed
from .state import CollectionOptions, CollectionRunState

# Playwright otherwise waits forever for document.fonts.ready on some ad pages.
os.environ["PW_TEST_SCREENSHOT_NO_FONTS_READY"] = "1"


def collect_feed(
    page: Any,
    ctx: Any,
    run_dir: Path,
    *,
    minutes: float,
    max_scrolls: int,
    shots: bool,
    do_resolve: bool,
    resolve_max: int,
    scroll_px: int,
    debug: DebugRecorder | None = None,
    feed_url: str = "https://m.facebook.com/",
    country: str | None = None,
    archive_landings: bool = True,
    landing_archive_timeout: float = 20.0,
    landing_archive_max_resources: int = 120,
    record_videos: bool = True,
    video_max_seconds: float = 30.0,
    video_fps: int = 8,
    max_ads_per_view: int = 1,
    resolve_post_urls: bool = True,
    interest_safe_mode: bool = False,
    stop_requested: Callable[[], bool] = global_stop_requested,
) -> dict[str, CollectedAd]:
    policy = ArtifactPolicy.from_options(
        screenshots=shots,
        landing_resolution=do_resolve,
        video_recording=record_videos,
        permalink_resolution=resolve_post_urls,
        interest_safe=interest_safe_mode,
    )
    options = CollectionOptions(
        run_dir=run_dir,
        minutes=minutes,
        max_scrolls=max_scrolls,
        screenshots=policy.screenshots,
        resolve_landings=policy.landing_resolution,
        resolve_max=resolve_max,
        scroll_px=scroll_px,
        debug=debug,
        feed_url=feed_url,
        country=country,
        archive_landings=archive_landings,
        landing_archive_timeout=landing_archive_timeout,
        landing_archive_max_resources=landing_archive_max_resources,
        record_videos=policy.video_recording,
        video_max_seconds=video_max_seconds,
        video_fps=video_fps,
        max_ads_per_view=max_ads_per_view,
        resolve_post_urls=policy.permalink_resolution,
        interest_safe_mode=interest_safe_mode,
        interest_safe_overrides=policy.overrides,
    )
    prepare_artifact_directories(options)
    started_at = utc_now()
    started_clock = time.time()
    state = CollectionRunState(
        options=options,
        service=CollectionService(),
        feed_reader=FeedReader(page, passive=interest_safe_mode),
        started_at=started_at,
        started_clock=started_clock,
        deadline=started_clock + minutes * 60,
        next_long_pause_scroll=random.randint(12, 18),
    )
    prepare_feed(page, state)
    try:
        collect_until_budget(page, ctx, state, stop_requested=stop_requested)
    except KeyboardInterrupt:
        state.interrupted = True
        print(f"[collect interrupted] saving {len(state.ads)} ads", flush=True)
        if debug:
            debug.event(
                "collect_interrupted",
                unique_ads=len(state.ads),
                resolved=state.resolved,
                scrolls=state.scrolls,
                refreshes=state.refreshes,
            )
    finally:
        write_ads(run_dir / "ads.partial.json", state.ads)
    return finalize_collection(page, state, stop_requested=stop_requested())


def prepare_artifact_directories(options: CollectionOptions) -> None:
    if options.screenshots:
        options.screenshots_dir.mkdir(parents=True, exist_ok=True)
    if options.record_videos:
        options.videos_dir.mkdir(parents=True, exist_ok=True)


def prepare_feed(page: Any, state: CollectionRunState) -> None:
    options = state.options
    state.passive_pre_navigation_guard = (
        prepare_passive_media_guard(page)
        if options.interest_safe_mode
        else {
            "init_script_installed": False,
            "media_route_installed": False,
            "blocked_media_requests": 0,
        }
    )
    goto_with_retry(page, options.feed_url, timeout=20000)
    state.passive_guard_installed = (
        install_passive_media_guard(page) if options.interest_safe_mode else False
    )
    time.sleep(4)
    state.facebook_login_required = facebook_login_required(page)
    if state.facebook_login_required:
        state.stop_reason = "facebook_login_required"
        print(
            "[collect stop] Facebook authentication is required for this profile",
            flush=True,
        )
    if options.debug:
        options.debug.event(
            "collect_started",
            minutes=options.minutes,
            max_scrolls=options.max_scrolls,
            resolve=options.resolve_landings,
            resolve_max=options.resolve_max,
            scroll_px=options.scroll_px,
            feed_url=DebugRecorder._page_url(page),
            facebook_login_required=state.facebook_login_required,
        )
        options.debug.screenshot(page, "viewports/start.png")


def collect_until_budget(
    page: Any,
    context: Any,
    state: CollectionRunState,
    *,
    stop_requested: Callable[[], bool],
) -> None:
    options = state.options
    while (
        not state.stop_reason
        and time.time() < state.deadline
        and state.scrolls < options.max_scrolls
    ):
        rows = detect_rows(page, state)
        new_ads_in_view = 0
        for row in rows:
            remaining_seconds = state.remaining_seconds(time.time())
            requested_stop = stop_requested()
            if remaining_seconds <= 5 or requested_stop:
                state.stop_reason = "interrupted" if requested_stop else "time_budget"
                break
            outcome = process_candidate(page, context, row, state)
            if outcome == "stop":
                break
            if outcome == "accepted":
                new_ads_in_view += 1
                if (
                    options.max_ads_per_view > 0
                    and new_ads_in_view >= options.max_ads_per_view
                ):
                    break
        if state.stop_reason:
            break
        if not advance_feed(
            page,
            context,
            state,
            detected_rows=len(rows),
        ):
            break


def detect_rows(page: Any, state: CollectionRunState) -> list[dict[str, Any]]:
    try:
        return cast(list[dict[str, Any]], state.feed_reader.detect())
    except Exception as exc:
        if state.options.debug:
            state.options.debug.event(
                "detect_error",
                scroll=state.scrolls,
                error=repr(exc),
                traceback=traceback.format_exc(),
                page_url=DebugRecorder._page_url(page),
            )
            state.options.debug.screenshot(
                page,
                f"errors/detect_{state.scrolls:06d}.png",
            )
        return []

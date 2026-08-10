from __future__ import annotations

import random
import time
from typing import Any

from app.facebook.feed import install_passive_media_guard
from app.facebook.navigation import goto_with_retry

from ...artifacts import write_ads
from .debug_recorder import DebugRecorder
from .state import CollectionRunState


def advance_feed(
    page: Any,
    context: Any,
    state: CollectionRunState,
    *,
    detected_rows: int,
) -> bool:
    options = state.options
    actual_scroll_px = max(260, int(options.scroll_px * random.uniform(0.75, 1.35)))
    if options.debug:
        options.debug.event(
            "scroll_start",
            scroll=state.scrolls + 1,
            scroll_px=actual_scroll_px,
            page_url=DebugRecorder._page_url(page),
            pages=len(context.pages),
        )
    try:
        state.feed_reader.scroll(actual_scroll_px)
    except Exception as exc:
        print(f"[collect stop] scroll failed: {exc}", flush=True)
        state.stop_reason = "scroll_failed"
        return False

    state.scrolls += 1
    time.sleep(random.uniform(1.9, 4.2))
    if state.scrolls >= state.next_long_pause_scroll:
        time.sleep(random.uniform(4.0, 8.0))
        state.next_long_pause_scroll = state.scrolls + random.randint(12, 18)
    if options.debug:
        options.debug.event(
            "scroll",
            scroll=state.scrolls,
            elapsed=round(time.time() - state.started_clock, 3),
            detected_rows=detected_rows,
            unique_ads=len(state.ads),
            resolved=state.resolved,
            refreshes=state.refreshes,
            page_url=DebugRecorder._page_url(page),
            pages=len(context.pages),
        )
    refresh_feed_if_needed(page, state)
    checkpoint_feed(page, state)
    return True


def refresh_feed_if_needed(page: Any, state: CollectionRunState) -> None:
    options = state.options
    stale_feed = state.scrolls - state.last_ad_scroll >= 90
    periodic_refresh = state.scrolls > 0 and state.scrolls % 180 == 0
    if not stale_feed and not periodic_refresh:
        return
    state.refreshes += 1
    if options.debug:
        options.debug.event(
            "refresh_start",
            scroll=state.scrolls,
            refreshes=state.refreshes,
            reason="stale_feed" if stale_feed else "periodic",
            page_url=DebugRecorder._page_url(page),
        )
        options.debug.screenshot(
            page,
            f"viewports/refresh_{state.scrolls:06d}.png",
        )
    try:
        goto_with_retry(page, options.feed_url, timeout=15000, attempts=3)
        if options.interest_safe_mode:
            state.passive_guard_installed = (
                install_passive_media_guard(page) or state.passive_guard_installed
            )
        time.sleep(random.uniform(5.0, 9.0))
    except Exception:
        pass
    state.last_ad_scroll = state.scrolls


def checkpoint_feed(page: Any, state: CollectionRunState) -> None:
    if state.scrolls > 3 and state.scrolls % 10 != 0:
        return
    options = state.options
    if options.debug:
        options.debug.screenshot(
            page,
            f"viewports/scroll_{state.scrolls:06d}.png",
        )
    write_ads(options.run_dir / "ads.partial.json", state.ads)
    print(
        f"[collect {int(time.time() - state.started_clock)}s "
        f"scroll {state.scrolls}] unique ads={len(state.ads)} "
        f"resolved={state.resolved} refreshes={state.refreshes}",
        flush=True,
    )

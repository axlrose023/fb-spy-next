from __future__ import annotations

import argparse
import traceback
from collections.abc import Callable
from pathlib import Path
from typing import Any, Protocol

from playwright.sync_api import sync_playwright

from app.facebook.enrichment import neutralize_profile_pages
from app.facebook.navigation import is_facebook_feed_url

from ..adapters.playwright import DebugRecorder
from ..models import CollectedAd
from .artifacts import write_ads


class FeedCollector(Protocol):
    def __call__(
        self,
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
    ) -> dict[str, CollectedAd]: ...


def run_browser_session(
    args: argparse.Namespace,
    *,
    ws_endpoint: str,
    run_dir: Path,
    feed_url: str,
    profile_country: str | None,
    debug: DebugRecorder,
    collect: FeedCollector,
    stop_requested: Callable[[], bool],
) -> dict[str, CollectedAd]:
    with sync_playwright() as playwright:
        browser = playwright.chromium.connect_over_cdp(ws_endpoint)
        context = browser.contexts[0]
        debug.attach_context(context)
        page = None
        if not args.topic.strip():
            page = next(
                (
                    candidate
                    for candidate in context.pages
                    if is_facebook_feed_url(candidate.url)
                ),
                None,
            )
        if page is None:
            page = context.new_page()
        interrupted = False
        try:
            ads = collect(
                page,
                context,
                run_dir,
                minutes=args.minutes,
                max_scrolls=args.collect_scrolls,
                shots=not args.no_shots,
                do_resolve=not args.no_resolve and not args.passive_collect,
                resolve_max=args.resolve_max,
                scroll_px=args.scroll_px,
                debug=debug if args.debug else None,
                feed_url=feed_url,
                country=profile_country,
                archive_landings=not args.no_landing_archives,
                landing_archive_timeout=args.landing_archive_timeout,
                landing_archive_max_resources=args.landing_archive_max_resources,
                record_videos=(
                    not args.no_video_recording and not args.passive_collect
                ),
                video_max_seconds=args.video_max_seconds,
                video_fps=args.video_fps,
                max_ads_per_view=args.max_ads_per_view,
                resolve_post_urls=not args.passive_collect,
                interest_safe_mode=args.passive_collect,
            )
            write_ads(run_dir / "ads.json", ads)
            if args.passive_collect:
                neutralize_profile_pages(page, context)
        except BaseException as exc:
            interrupted = isinstance(exc, KeyboardInterrupt)
            debug.event(
                "fatal",
                error=repr(exc),
                traceback=traceback.format_exc(),
                page_url=DebugRecorder._page_url(page),
                pages=[
                    DebugRecorder._page_url(candidate) for candidate in context.pages
                ],
            )
            if not interrupted:
                debug.screenshot(page, "errors/fatal.png")
            raise
        finally:
            if interrupted or stop_requested():
                debug.event("debug_cleanup_skipped", reason="keyboard_interrupt")
            else:
                debug.finish_context(context)
                debug.event(
                    "browser_left_active_for_followup",
                    passive_collect=args.passive_collect,
                    page_url=DebugRecorder._page_url(page),
                )
    return ads

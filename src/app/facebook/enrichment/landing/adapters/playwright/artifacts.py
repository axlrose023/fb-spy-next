from __future__ import annotations

from pathlib import Path
from typing import Any

from app.facebook.collection import CollectedAd
from app.facebook.navigation import is_facebook_feed_url

from ....media import (
    archive_landing_page_from_browser,
    save_landing_screenshot_from_browser,
    wait_for_landing_page_ready,
)
from ...urls import parse_landing
from .diagnostics import DebugRecorderPort, page_url


def capture_landing_artifacts(
    ad: CollectedAd,
    full: str,
    *,
    new_page: Any | None,
    page: Any,
    run_dir: Path,
    debug: DebugRecorderPort | None,
    debug_id: int,
    archive_landing: bool,
    timeout: float,
    max_resources: int,
) -> None:
    clean, tracking, ad_id = parse_landing(full)
    ad.landing_full, ad.landing_clean, ad.utm = full, clean, tracking
    ad.fb_ad_id = ad_id or ad.fb_ad_id
    archive_page = new_page
    if archive_page is None and not is_facebook_feed_url(page_url(page)):
        archive_page = page
    screenshot_path = None
    if archive_page is not None:
        try:
            wait_for_landing_page_ready(archive_page, timeout_seconds=timeout)
            screenshot_path = save_landing_screenshot_from_browser(
                archive_page,
                run_dir,
                source_index=debug_id,
                domain=ad.displayed_domain,
                url=full,
                timeout_seconds=timeout,
                wait_until_ready=False,
            )
            if screenshot_path:
                ad.landing_screenshot = screenshot_path
                if debug:
                    debug.event(
                        "landing_screenshot_saved",
                        debug_id=debug_id,
                        screenshot=screenshot_path,
                    )
        except Exception as exc:
            print(
                f"  landing screenshot failed {ad.displayed_domain}: {exc!r}",
                flush=True,
            )
            if debug:
                debug.event(
                    "landing_screenshot_failed",
                    debug_id=debug_id,
                    error=repr(exc),
                )
    if archive_landing and archive_page is not None:
        try:
            archive_path = archive_landing_page_from_browser(
                archive_page,
                run_dir,
                source_index=debug_id,
                domain=ad.displayed_domain,
                url=full,
                timeout_seconds=timeout,
                max_resources=max_resources,
                wait_until_ready=False,
                fallback_screenshot_path=(
                    run_dir / screenshot_path if screenshot_path else None
                ),
            )
            if archive_path:
                ad.landing_archive = archive_path
                print(f"  archived {ad.displayed_domain} -> {archive_path}", flush=True)
                if debug:
                    debug.event(
                        "landing_archived",
                        debug_id=debug_id,
                        archive=archive_path,
                    )
        except Exception as exc:
            print(f"  archive failed {ad.displayed_domain}: {exc!r}", flush=True)
            if debug:
                debug.event(
                    "landing_archive_failed",
                    debug_id=debug_id,
                    error=repr(exc),
                )

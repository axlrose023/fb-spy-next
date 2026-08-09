from __future__ import annotations

import time
import traceback
from pathlib import Path
from typing import Any

from app.facebook.collection import CollectedAd
from app.facebook.navigation import recover_facebook_feed

from ...urls import external_landing_url
from .artifacts import capture_landing_artifacts
from .cta import SCROLL_CTA_JS
from .diagnostics import DebugRecorderPort, page_url
from .tabs import close_landing_tabs


def resolve_in_view(
    page: Any,
    ctx: Any,
    ad: CollectedAd,
    btn: dict[str, Any] | None,
    element_id: str | None,
    run_dir: Path,
    debug: DebugRecorderPort | None = None,
    debug_id: int = 0,
    feed_url: str = "https://m.facebook.com/",
    archive_landing: bool = True,
    landing_archive_timeout: float = 20.0,
    landing_archive_max_resources: int = 120,
) -> None:
    """Click a visible ad CTA, capture its landing, then restore the feed."""
    prefix = f"resolve/{debug_id:04d}"
    if debug:
        debug.event(
            "resolve_start",
            debug_id=debug_id,
            advertiser=ad.advertiser,
            domain=ad.displayed_domain,
            element_id=element_id,
            feed_url=page_url(page),
            pages=[page_url(candidate) for candidate in ctx.pages],
        )
        debug.screenshot(page, f"{prefix}_before.png")
    close_landing_tabs(ctx, keep=page)
    payload = {"domain": ad.displayed_domain, "element_id": element_id or ""}
    fresh = page.evaluate(SCROLL_CTA_JS, payload)
    if not fresh:
        if debug:
            debug.event("resolve_no_cta", debug_id=debug_id, payload=payload)
            debug.screenshot(page, f"{prefix}_no_cta.png")
        return
    time.sleep(0.8)
    fresh = page.evaluate(SCROLL_CTA_JS, payload) or fresh
    full = None
    new_page = None
    try:
        with ctx.expect_page(timeout=8000) as new_info:
            page.locator('[data-fbspy-cta="1"]').first.click(
                timeout=1500,
                no_wait_after=True,
            )
        new_page = new_info.value
        try:
            new_page.wait_for_load_state("domcontentloaded", timeout=12000)
        except Exception:
            pass
        time.sleep(1.0)
        landing_url = new_page.url
        full = external_landing_url(landing_url)
        if debug:
            debug.event(
                "resolve_new_page",
                debug_id=debug_id,
                url=landing_url,
                external=full,
                pages=[page_url(candidate) for candidate in ctx.pages],
            )
            debug.screenshot(new_page, f"{prefix}_landing.png")
    except Exception as exc:
        full, new_page = _recover_clicked_landing(
            page,
            ctx,
            debug=debug,
            debug_id=debug_id,
            prefix=prefix,
            error=exc,
            traceback_text=traceback.format_exc(),
        )
    if full:
        capture_landing_artifacts(
            ad,
            full,
            new_page=new_page,
            page=page,
            run_dir=run_dir,
            debug=debug,
            debug_id=debug_id,
            archive_landing=archive_landing,
            timeout=landing_archive_timeout,
            max_resources=landing_archive_max_resources,
        )
    _finish_landing_capture(
        page,
        ctx,
        ad,
        new_page=new_page,
        feed_url=feed_url,
        debug=debug,
        debug_id=debug_id,
        prefix=prefix,
    )


def _recover_clicked_landing(
    page: Any,
    context: Any,
    *,
    debug: DebugRecorderPort | None,
    debug_id: int,
    prefix: str,
    error: Exception,
    traceback_text: str,
) -> tuple[str | None, Any | None]:
    full = None
    new_page = None
    try:
        time.sleep(1.0)
        full = external_landing_url(page.url)
    except Exception:
        pass
    if not full:
        for candidate in reversed(list(context.pages)):
            if candidate == page or page_url(candidate).startswith("devtools"):
                continue
            candidate_url = page_url(candidate)
            recovered = external_landing_url(candidate_url)
            if recovered:
                new_page, full = candidate, recovered
                if debug:
                    debug.event(
                        "resolve_recovered_page",
                        debug_id=debug_id,
                        url=candidate_url,
                        external=full,
                    )
                    debug.screenshot(candidate, f"{prefix}_recovered_landing.png")
                break
    if debug:
        details = {
            "debug_id": debug_id,
            "feed_url": page_url(page),
            "pages": [page_url(candidate) for candidate in context.pages],
        }
        if full:
            debug.event(
                "resolve_click_timeout_recovered",
                timeout=repr(error),
                external=full,
                **details,
            )
        else:
            debug.event(
                "resolve_click_error",
                error=repr(error),
                traceback=traceback_text,
                **details,
            )
            debug.screenshot(page, f"{prefix}_click_error.png")
    return full, new_page


def _finish_landing_capture(
    page: Any,
    context: Any,
    ad: CollectedAd,
    *,
    new_page: Any | None,
    feed_url: str,
    debug: DebugRecorderPort | None,
    debug_id: int,
    prefix: str,
) -> None:
    try:
        if new_page and not new_page.is_closed():
            new_page.close(run_before_unload=False)
    except Exception:
        pass
    close_landing_tabs(context, keep=page)
    try:
        page.keyboard.press("Escape")
    except Exception:
        pass
    recover_facebook_feed(page, feed_url=feed_url)
    if debug:
        debug.event(
            "resolve_finish",
            debug_id=debug_id,
            full=ad.landing_full,
            clean=ad.landing_clean,
            fb_ad_id=ad.fb_ad_id,
            feed_url=page_url(page),
            pages=[page_url(candidate) for candidate in context.pages],
        )
        debug.screenshot(page, f"{prefix}_after.png")

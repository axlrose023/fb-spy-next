from __future__ import annotations

import time
from pathlib import Path
from typing import Any

from playwright.sync_api import Error as PlaywrightError

from app.facebook.calibration import wait_for_saved_post
from app.facebook.navigation import goto_with_retry
from app.services import facebook_runner

from ...models import EnrichmentOptions, EnrichmentResult, RelevantAd
from ...post import valid_post_url
from .landing import resolve_landing
from .mapping import ad_from_raw, merge_ad_fields, target_from_raw
from .post import recover_allowed_post_url
from .video import record_video


class PlaywrightRelevantAdExecutor:
    def __init__(self, options: EnrichmentOptions) -> None:
        self._options = options

    def enrich(
        self,
        context: Any,
        ad: RelevantAd,
        *,
        sequence: int,
        run_dir: Path,
    ) -> EnrichmentResult:
        return enrich_allowed_ad(
            context,
            ad,
            sequence=sequence,
            run_dir=run_dir,
            options=self._options,
        )


def enrich_allowed_ad(
    context: Any,
    candidate: RelevantAd,
    *,
    sequence: int,
    run_dir: Path,
    options: EnrichmentOptions,
) -> EnrichmentResult:
    enriched = dict(candidate.raw)
    post_url = valid_post_url(enriched.get("facebook_post_url"))
    details = _initial_details(post_url)
    if not post_url:
        post_url, recovery = recover_allowed_post_url(
            context,
            enriched,
            options=options,
        )
        details["post_url_recovery"] = recovery
        details["active_actions_started"] = bool(
            recovery.get("profile_navigation_started")
        )
        details["post_url"] = post_url
        if not post_url:
            details["status"] = "skipped_missing_passive_post_url"
            enriched["enrichment"] = details
            return EnrichmentResult(enriched, details)
        enriched["facebook_post_url"] = post_url
    page = None
    started = time.monotonic()
    try:
        page = context.new_page()
        details["active_actions_started"] = True
        _open_saved_post(page, post_url, options)
        located = wait_for_saved_post(
            page,
            target_from_raw(enriched, post_url),
            timeout_ms=max(0, options.locate_timeout_ms),
        )
        details["match"] = located
        if located.get("status") != "located":
            raise RuntimeError(f"saved Facebook post not found: {located}")
        element_id = str(located["element_id"])
        ad = ad_from_raw(enriched, element_id=element_id)
        _capture_video(page, ad, element_id, details, sequence, run_dir, options)
        _capture_landing(
            page,
            context,
            ad,
            element_id,
            details,
            post_url,
            sequence,
            run_dir,
            options,
        )
        merge_ad_fields(enriched, ad)
        details["status"] = "completed"
    except Exception as exc:
        details["status"] = "failed"
        details["error"] = repr(exc)
        details["infrastructure_error"] = is_infrastructure_error(exc)
    finally:
        details["duration_seconds"] = round(time.monotonic() - started, 3)
        _close_page(page, details)
    enriched["enrichment"] = details
    return EnrichmentResult(enriched, details)


def _initial_details(post_url: str) -> dict[str, Any]:
    return {
        "status": "pending",
        "active_actions_started": False,
        "post_url": post_url,
        "post_url_recovery": None,
        "video_attempted": False,
        "video_recorded": False,
        "cta_click_attempted": False,
        "landing_resolved": False,
        "error": None,
    }


def _open_saved_post(page: Any, post_url: str, options: EnrichmentOptions) -> None:
    response = goto_with_retry(
        page,
        post_url,
        timeout=max(1, options.timeout_ms),
        attempts=3,
    )
    if response and response.status >= 400:
        raise RuntimeError(f"saved Facebook post returned HTTP {response.status}")
    if options.wait_after_load > 0:
        page.wait_for_timeout(round(options.wait_after_load * 1000))


def _capture_video(
    page: Any,
    ad: facebook_runner.Ad,
    element_id: str,
    details: dict[str, Any],
    sequence: int,
    run_dir: Path,
    options: EnrichmentOptions,
) -> None:
    if not options.record_videos or not ad.has_video:
        return
    details["video_attempted"] = True
    ok, issue = record_video(
        page,
        ad,
        element_id,
        sequence=sequence,
        run_dir=run_dir,
        options=options,
    )
    details.update({"video_recorded": ok, "video_issue": issue})


def _capture_landing(
    page: Any,
    context: Any,
    ad: facebook_runner.Ad,
    element_id: str,
    details: dict[str, Any],
    post_url: str,
    sequence: int,
    run_dir: Path,
    options: EnrichmentOptions,
) -> None:
    if not options.resolve_landings or ad.ad_type != "link" or not ad.displayed_domain:
        return
    details["cta_click_attempted"] = True
    resolve_landing(
        page,
        context,
        ad,
        element_id,
        post_url=post_url,
        sequence=sequence,
        run_dir=run_dir,
        options=options,
    )
    details["landing_resolved"] = bool(ad.landing_full)


def _close_page(page: Any, details: dict[str, Any]) -> None:
    if page is None:
        return
    facebook_runner._pause_ad_video(
        page,
        str(details.get("match", {}).get("element_id") or ""),
    )
    try:
        page.close(run_before_unload=False)
    except PlaywrightError:
        pass


def is_infrastructure_error(exc: Exception) -> bool:
    return any(
        marker in str(exc)
        for marker in (
            "Target page, context or browser has been closed",
            "BrowserContext.new_page: Target page, context or browser has been closed",
            "ERR_SOCKS_CONNECTION_FAILED",
            "ERR_PROXY_CONNECTION_FAILED",
            "ERR_NETWORK_CHANGED",
            "ERR_CONNECTION_RESET",
            "ERR_CONNECTION_CLOSED",
            "ERR_TIMED_OUT",
        )
    )

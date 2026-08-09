from __future__ import annotations

import time
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

from playwright.sync_api import Error as PlaywrightError

from app.facebook.enrichment import (
    archive_landing_page_from_browser,
    parse_landing,
    save_landing_screenshot_from_browser,
    wait_for_landing_page_ready,
)

from ..evidence.policy import isolated_external_url
from .anonymous_post import resolve_from_anonymous_post
from .isolation import NetworkGuard, host_is_public


def resolve_landing(
    context: Any,
    raw: dict[str, Any],
    target: str,
    *,
    source: str,
    sequence: int,
    run_dir: Path,
    args: Any,
    network_guard: NetworkGuard,
    facebook_cookie_count_before: int,
) -> tuple[dict[str, Any], dict[str, Any]]:
    resolved = dict(raw)
    started = time.monotonic()
    blocked_meta_before = network_guard.meta_requests_blocked
    blocked_private_before = network_guard.private_requests_blocked
    result = _initial_result(source, target, facebook_cookie_count_before)
    page = None
    try:
        page = context.new_page()
        if source == "anonymous_facebook_post":
            resolve_from_anonymous_post(
                page,
                context,
                resolved,
                result,
                target,
                sequence=sequence,
                run_dir=run_dir,
                args=args,
            )
        else:
            _capture_direct_landing(
                page,
                resolved,
                raw,
                target,
                sequence=sequence,
                run_dir=run_dir,
                args=args,
                result=result,
            )
        result["status"] = "completed"
        result["landing_resolved"] = True
        result["landing_screenshot_saved"] = bool(resolved.get("landing_screenshot"))
        result["landing_archive_saved"] = bool(resolved.get("landing_archive"))
    except Exception as exc:
        result["status"] = "failed"
        result["error"] = repr(exc)
    finally:
        result["duration_seconds"] = round(time.monotonic() - started, 3)
        result["meta_requests_blocked"] = (
            network_guard.meta_requests_blocked - blocked_meta_before
        )
        result["private_requests_blocked"] = (
            network_guard.private_requests_blocked - blocked_private_before
        )
        if page is not None:
            try:
                page.close(run_before_unload=False)
            except PlaywrightError:
                pass
    resolved["isolated_resolution"] = result
    return resolved, result


def reuse_resolution(
    target: dict[str, Any],
    cached: dict[str, Any],
    *,
    source_row_index: int,
) -> None:
    source = cached["row"]
    for key in (
        "landing_full",
        "landing_clean",
        "landing_screenshot",
        "landing_archive",
        "fb_ad_id",
        "utm",
    ):
        if source.get(key):
            target[key] = source[key]
    source_result = source.get("isolated_resolution")
    target["isolated_resolution"] = {
        "status": "reused_isolated_result",
        "cookie_isolated": True,
        "separate_browser_context": True,
        "facebook_cookie_count_before": 0,
        "authenticated_profile_context": False,
        "active_profile_actions_started": False,
        "isolated_navigation_started": False,
        "external_navigation_started": False,
        "anonymous_facebook_navigation_started": False,
        "isolated_click_attempted": False,
        "source": (
            source_result.get("source") if isinstance(source_result, dict) else "reused"
        ),
        "source_row_index": source_row_index,
        "landing_resolved": bool(target.get("landing_full")),
        "landing_screenshot_saved": bool(target.get("landing_screenshot")),
        "landing_archive_saved": bool(target.get("landing_archive")),
        "source_status": (
            source_result.get("status") if isinstance(source_result, dict) else None
        ),
        "meta_requests_blocked": 0,
        "private_requests_blocked": 0,
    }


def _capture_direct_landing(
    page: Any,
    resolved: dict[str, Any],
    raw: dict[str, Any],
    target: str,
    *,
    sequence: int,
    run_dir: Path,
    args: Any,
    result: dict[str, Any],
) -> None:
    result["isolated_navigation_started"] = True
    result["external_navigation_started"] = True
    response = page.goto(
        target,
        wait_until="domcontentloaded",
        timeout=max(1, args.timeout_ms),
        referer="",
    )
    if response and response.status >= 400:
        raise RuntimeError(f"landing returned HTTP {response.status}")
    wait_for_landing_page_ready(
        page,
        timeout_seconds=max(1.0, args.landing_ready_seconds),
    )
    final_url, issue = isolated_external_url(
        page.url,
        host_is_public=host_is_public,
    )
    if not final_url:
        raise RuntimeError(f"unsafe landing redirect: {issue}")
    clean, utm, ad_id = parse_landing(final_url)
    resolved.update({"landing_full": final_url, "landing_clean": clean, "utm": utm})
    if ad_id and not resolved.get("fb_ad_id"):
        resolved["fb_ad_id"] = ad_id
    screenshot = save_landing_screenshot_from_browser(
        page,
        run_dir,
        source_index=sequence,
        domain=str(raw.get("displayed_domain") or ""),
        url=final_url,
        timeout_seconds=max(1.0, args.landing_ready_seconds),
        wait_until_ready=False,
    )
    if screenshot:
        resolved["landing_screenshot"] = screenshot
    if args.archive_landings:
        archive = archive_landing_page_from_browser(
            page,
            run_dir,
            source_index=sequence,
            domain=str(raw.get("displayed_domain") or ""),
            url=final_url,
            timeout_seconds=max(1.0, args.landing_ready_seconds),
            max_resources=max(1, args.landing_archive_max_resources),
            wait_until_ready=False,
            fallback_screenshot_path=run_dir / screenshot if screenshot else None,
        )
        if archive:
            resolved["landing_archive"] = archive


def _initial_result(
    source: str,
    target: str,
    cookie_count: int,
) -> dict[str, Any]:
    return {
        "status": "pending",
        "cookie_isolated": True,
        "separate_browser_context": True,
        "facebook_cookie_count_before": cookie_count,
        "authenticated_profile_context": False,
        "active_profile_actions_started": False,
        "isolated_navigation_started": False,
        "external_navigation_started": False,
        "anonymous_facebook_navigation_started": False,
        "isolated_click_attempted": False,
        "source": source,
        "target_host": urlsplit(target).hostname,
    }

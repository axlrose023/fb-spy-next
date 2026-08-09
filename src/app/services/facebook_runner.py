"""Facebook ad-spy runner (standalone, single file).

Connects to a RUNNING Octo Browser profile over CDP and harvests the sponsored
posts shown in that account's mobile Facebook feed. Ad detection is
LANGUAGE-INDEPENDENT (no word lists, no OCR): Facebook marks every sponsored
post's secondary line with private-use-area icon glyphs (U+F17E1 / U+F078B).
We key off those glyphs, which are identical in every locale.

Collected data is written before any click, so a fragile click can never lose
it:
  - For every ad we read (no interaction): advertiser, displayed domain,
    headline, ad text, CTA, creative image, screenshot, destination type, and
    whether the creative contains video. The feed is auto-refreshed (Home)
    when it bottoms out.
  - For link-type ads we then click the CTA inline, wait for the landing tab
    to settle (slow proxies!), capture the FULL url with all utm / fbclid /
    ad-id params, and close the tab. In-FB destinations (video/lead form) open
    no external tab and are skipped without breaking the run.

Ad detection is language-independent: no "Sponsored" word list, no OCR, no
hardcoded CDN paths — only the sponsored glyphs and structural cues.

Prereqs: the Octo profile must already be STARTED. The runner restarts it with
a debug port if needed, then talks to it via Playwright connect_over_cdp.

Usage:
    python fb_spy/runner.py --minutes 10 --out fb_spy/results
    python fb_spy/runner.py --minutes 5 --no-resolve          # collect only
    python fb_spy/runner.py --collect-scrolls 200 --resolve-max 80
"""

from __future__ import annotations

import argparse
import json
import os
import random
import re
import signal
import sys
import time
import traceback
from collections.abc import Sequence
from dataclasses import asdict
from datetime import datetime
from pathlib import Path
from urllib.parse import quote_plus

from playwright.sync_api import sync_playwright

from app.browser import (
    BrowserOperationDeadlineExceeded as _OperationDeadlineExceeded,
)
from app.browser import hard_deadline as _hard_deadline
from app.facebook import enrichment as facebook_enrichment
from app.facebook import navigation as facebook_navigation
from app.facebook.adapters.octo import (
    OctoHttpClient,
    OctoProfileSessionManager,
)
from app.facebook.adapters.octo import (
    rewrite_cdp_endpoint_host as _rewrite_cdp_endpoint_host,
)
from app.facebook.collection import (
    ArtifactPolicy,
    CollectionService,
    ad_summary,
    creative_identity,
    is_lazy_video_image,
    normalize_fingerprint_text,
)
from app.facebook.collection import (
    CollectedAd as Ad,
)
from app.facebook.collection import (
    utc_now as collection_utc_now,
)
from app.facebook.collection.adapters import playwright as collection_playwright
from app.facebook.collection.adapters.playwright import (
    BAD_DOMAINS as COLLECTION_BAD_DOMAINS,
)
from app.facebook.collection.adapters.playwright import (
    DETECT_JS as COLLECTION_DETECT_JS,
)
from app.facebook.collection.adapters.playwright import (
    PASSIVE_MEDIA_GUARD_INSTALL_JS as COLLECTION_PASSIVE_MEDIA_GUARD_INSTALL_JS,
)
from app.facebook.collection.adapters.playwright import (
    DebugRecorder,
    FeedReader,
    install_passive_media_guard,
    prepare_passive_media_guard,
)
from app.facebook.collection.adapters.playwright import (
    passive_media_guard_stats as _passive_media_guard_stats,
)
from app.facebook.enrichment.landing.adapters import (
    playwright as landing_playwright,
)
from app.facebook.enrichment.video.adapters import (
    playwright as video_playwright,
)
from app.facebook.profiles import (
    ProfileSourceError,
)
from app.facebook.profiles import (
    normalize_country as _normalize_country,
)

# Playwright waits for document.fonts.ready before every screenshot. Some ad
# pages keep remote fonts pending forever, which can wedge the sync driver even
# after the screenshot timeout. Capturing with a fallback font is preferable to
# aborting the whole collection cycle.
os.environ["PW_TEST_SCREENSHOT_NO_FONTS_READY"] = "1"

OCTO_API = "http://127.0.0.1:58888"   # Octo Local API; override with --octo-host/--octo-port
OCTO_PROFILE_UUID = "replace-with-octo-profile-uuid"
OCTO_HEADLESS = False
COLLECTOR_METRIC_VERSION = 2
OCTO_START_FLAGS = [
    "--no-sandbox",
    "--disable-gpu",
    "--disable-dev-shm-usage",
    "--remote-debugging-address=0.0.0.0",
]
STOP_REQUESTED = False
TRANSIENT_NAVIGATION_ERRORS = facebook_navigation.TRANSIENT_NAVIGATION_ERRORS
PROXY_CERTIFICATE_AUTHORITY_ERROR = (
    facebook_navigation.PROXY_CERTIFICATE_AUTHORITY_ERROR
)
_facebook_login_required = facebook_navigation.facebook_login_required
_goto_with_retry = facebook_navigation.goto_with_retry
_ignore_proxy_certificate_errors = facebook_navigation.ignore_proxy_certificate_errors
_is_fb_feed_url = facebook_navigation.is_facebook_feed_url
_recover_feed = facebook_navigation.recover_facebook_feed
OPEN_COMMENTS_FOR_PERMALINK_JS = (
    facebook_enrichment.OPEN_COMMENTS_FOR_PERMALINK_JS
)
parse_landing = facebook_enrichment.parse_landing
_external_landing_url = facebook_enrichment.external_landing_url
_facebook_post_identity_from_url = (
    facebook_enrichment.facebook_post_identity_from_url
)
_normalized_facebook_post_url = (
    facebook_enrichment.normalized_facebook_post_url
)
resolve_facebook_post_url = facebook_enrichment.resolve_facebook_post_url
SCROLL_CTA_JS = landing_playwright.SCROLL_CTA_JS
_close_landing_tabs = landing_playwright.close_landing_tabs
neutralize_profile_pages = landing_playwright.neutralize_profile_pages
resolve_in_view = landing_playwright.resolve_in_view
MEDIA_READY_JS = collection_playwright.MEDIA_READY_JS
VIDEO_CREATIVE_JS = collection_playwright.VIDEO_CREATIVE_JS
_screenshot_has_blank_media = collection_playwright.screenshot_has_blank_media
save_ad_screenshot = collection_playwright.save_ad_screenshot
has_video_creative = collection_playwright.has_video_creative
_pause_all_videos = collection_playwright.pause_all_videos
BROWSER_OPERATION_TIMEOUT_REASONS = frozenset({
    "resolve_timeout",
    "video_timeout",
})
BAD_DOMAINS = COLLECTION_BAD_DOMAINS
DETECT_JS = COLLECTION_DETECT_JS
PASSIVE_MEDIA_GUARD_INSTALL_JS = COLLECTION_PASSIVE_MEDIA_GUARD_INSTALL_JS

# Sponsored marker glyphs (private use area). Language-independent.
GLYPHS = [0xF17E1, 0xF078B]

def utc_now() -> str:
    return collection_utc_now()


def _norm_fingerprint_text(value: str) -> str:
    return normalize_fingerprint_text(value)


def _creative_identity(url: str) -> str:
    return creative_identity(url)


def _is_lazy_video_image(url: str, *, has_video: bool, creative_area: int) -> bool:
    return is_lazy_video_image(
        url,
        has_video=has_video,
        creative_area=creative_area,
    )


def _request_stop(signum, _frame) -> None:
    global STOP_REQUESTED
    STOP_REQUESTED = True
    raise KeyboardInterrupt(f"signal {signum}")


# ── Octo Local API ────────────────────────────────────────────────────────
class OctoApiError(RuntimeError):
    pass


def octo(method: str, path: str, body: dict | None = None) -> dict | list:
    try:
        timeout = 150 if method == "POST" and path == "/api/profiles/start" else 40
        return OctoHttpClient(OCTO_API).request(
            method,
            path,
            body,
            timeout_seconds=timeout,
        )
    except ProfileSourceError as exc:
        raise OctoApiError(str(exc)) from exc


class _RunnerOctoTransport:
    def request(
        self,
        method: str,
        path: str,
        body: dict | None = None,
        *,
        timeout_seconds: float | None = None,
    ) -> dict | list:
        del timeout_seconds
        return octo(method, path, body)


def _profile_sessions() -> OctoProfileSessionManager:
    return OctoProfileSessionManager(
        _RunnerOctoTransport(),
        start_flags=OCTO_START_FLAGS,
        sleeper=time.sleep,
    )


def _start_octo_profile(uuid: str) -> tuple[str, dict]:
    session = _profile_sessions().start(uuid, headless=OCTO_HEADLESS)
    return session.ws_endpoint, session.connection.to_legacy_dict()


def get_cdp_endpoint() -> tuple[str, dict]:
    session = _profile_sessions().acquire(
        OCTO_PROFILE_UUID,
        headless=OCTO_HEADLESS,
    )
    return session.ws_endpoint, session.connection.to_legacy_dict()


def rewrite_cdp_endpoint_host(ws_endpoint: str, octo_host: str) -> str:
    return _rewrite_cdp_endpoint_host(ws_endpoint, octo_host)


def _write_ads(path: Path, ads: dict[str, Ad]) -> None:
    payload = json.dumps([asdict(a) for a in ads.values()],
                         ensure_ascii=False, indent=2)
    _write_text_atomic(path, payload)


def _write_json_atomic(path: Path, payload: dict | list) -> None:
    _write_text_atomic(path, json.dumps(payload, ensure_ascii=False, indent=2))


def _write_text_atomic(path: Path, payload: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(payload, encoding="utf-8")
    tmp.replace(path)


def _write_run_meta(run_dir: Path, payload: dict) -> None:
    _write_json_atomic(run_dir / "run_meta.json", payload)


def _fast_exit_after_browser_operation_timeout(run_dir: Path) -> None:
    """Avoid a wedged Playwright shutdown after SIGALRM interrupted its driver."""
    try:
        summary = json.loads((run_dir / "summary.json").read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return
    reason = str(summary.get("stop_reason") or "")
    if reason not in BROWSER_OPERATION_TIMEOUT_REASONS:
        return
    print(
        f"[runner] {reason} artifacts saved; exiting before Playwright cleanup",
        flush=True,
    )
    sys.stdout.flush()
    sys.stderr.flush()
    os._exit(0)


def _octo_start_failure_reason(error: BaseException) -> str:
    if "profiles.proxy_error" in str(error):
        return "octo_proxy_error"
    return "octo_start_error"


def _write_octo_start_failure(
    run_dir: Path,
    *,
    profile_uuid: str,
    octo_host: str,
    octo_port: int,
    octo_headless: bool,
    requested_minutes: float,
    started_at: str,
    elapsed_seconds: float,
    error: BaseException,
) -> str:
    reason = _octo_start_failure_reason(error)
    finished_at = utc_now()
    _write_run_meta(run_dir, {
        "collector_metric_version": COLLECTOR_METRIC_VERSION,
        "octo_profile_uuid": profile_uuid,
        "octo_host": octo_host,
        "octo_port": octo_port,
        "octo_headless": octo_headless,
        "started_at": started_at,
        "finished_at": finished_at,
        "start_failure": reason,
    })
    _write_json_atomic(run_dir / "summary.json", {
        "collector_metric_version": COLLECTOR_METRIC_VERSION,
        "requested_minutes": requested_minutes,
        "started_at": started_at,
        "finished_at": finished_at,
        "elapsed_seconds": max(0.0, elapsed_seconds),
        "scrolls": 0,
        "refreshes": 0,
        "captured_candidates": 0,
        "stop_reason": reason,
    })
    return reason


def _ad_summary(ads: dict[str, Ad]) -> dict:
    return ad_summary(ads)


def normalize_country(value: str | None) -> str | None:
    return _normalize_country(value)


VIDEO_PREP_JS = video_playwright.VIDEO_PREP_JS
record_ad_video = video_playwright.record_ad_video
_pause_ad_video = video_playwright.pause_ad_video
_capture_screencast_frames = video_playwright.capture_screencast_frames
_write_screencast_frame = video_playwright.write_screencast_frame
_prepare_video_playback = video_playwright.prepare_video_playback
_element_viewport_clip = video_playwright.element_viewport_clip
_trim_static_tail_frames = video_playwright.trim_static_tail_frames
_encode_video_frames = video_playwright.encode_video_frames
# ── Phase 1: collect (with inline resolve) ──────────────────────────────────
def collect(page, ctx, run_dir: Path, *, minutes: float, max_scrolls: int,
            shots: bool, do_resolve: bool, resolve_max: int, scroll_px: int,
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
            interest_safe_mode: bool = False) -> dict[str, Ad]:
    artifact_policy = ArtifactPolicy.from_options(
        screenshots=shots,
        landing_resolution=do_resolve,
        video_recording=record_videos,
        permalink_resolution=resolve_post_urls,
        interest_safe=interest_safe_mode,
    )
    interest_safe_overrides = list(artifact_policy.overrides)
    shots = artifact_policy.screenshots
    do_resolve = artifact_policy.landing_resolution
    record_videos = artifact_policy.video_recording
    resolve_post_urls = artifact_policy.permalink_resolution
    shots_dir = run_dir / "screens"
    if shots:
        shots_dir.mkdir(parents=True, exist_ok=True)
    videos_dir = run_dir / "videos"
    if record_videos:
        videos_dir.mkdir(parents=True, exist_ok=True)
    collection_service = CollectionService()
    feed_reader = FeedReader(page, passive=interest_safe_mode)
    ads = collection_service.registry.ads
    resolved = 0
    captured = 0
    duplicate_fb_ad_ids = 0
    resolve_timeouts = 0
    video_timeouts = 0
    cta_click_attempts = 0
    video_play_attempts = 0
    comment_open_attempts = 0
    started_at = utc_now()
    t0 = time.time()
    deadline = t0 + minutes * 60
    scrolls = refreshes = 0
    last_ad_scroll = 0
    next_long_pause_scroll = random.randint(12, 18)
    interrupted = False
    stop_reason = ""
    passive_pre_navigation_guard = (
        prepare_passive_media_guard(page)
        if interest_safe_mode
        else {
            "init_script_installed": False,
            "media_route_installed": False,
            "blocked_media_requests": 0,
        }
    )
    _goto_with_retry(page, feed_url, timeout=20000)
    passive_media_guard_installed = (
        install_passive_media_guard(page) if interest_safe_mode else False
    )
    time.sleep(4)
    facebook_login_required = _facebook_login_required(page)
    if facebook_login_required:
        stop_reason = "facebook_login_required"
        print(
            "[collect stop] Facebook authentication is required for this profile",
            flush=True,
        )
    if debug:
        debug.event("collect_started", minutes=minutes, max_scrolls=max_scrolls,
                    resolve=do_resolve, resolve_max=resolve_max, scroll_px=scroll_px,
                    feed_url=DebugRecorder._page_url(page),
                    facebook_login_required=facebook_login_required)
        debug.screenshot(page, "viewports/start.png")
    try:
        while not stop_reason and time.time() < deadline and scrolls < max_scrolls:
            try:
                rows = feed_reader.detect()
            except Exception as exc:
                rows = []
                if debug:
                    debug.event("detect_error", scroll=scrolls, error=repr(exc),
                                traceback=traceback.format_exc(),
                                page_url=DebugRecorder._page_url(page))
                    debug.screenshot(page, f"errors/detect_{scrolls:06d}.png")
            new_ads_in_view = 0
            for r in rows:
                remaining_seconds = deadline - time.time()
                if remaining_seconds <= 5 or STOP_REQUESTED:
                    stop_reason = "interrupted" if STOP_REQUESTED else "time_budget"
                    break
                decision = collection_service.consider_detection(r, country=country)
                ad = decision.ad
                key = decision.key
                coarse_key = decision.coarse_key
                creative_area = int(r.get("creative_area") or 0)
                if not decision.accepted and decision.reason == "confirmed_duplicate":
                    if debug:
                        debug.event(
                            "confirmed_duplicate_skip",
                            scroll=scrolls,
                            coarse_key=coarse_key,
                            advertiser=ad.advertiser,
                            domain=ad.displayed_domain,
                        )
                    continue
                if not decision.accepted and decision.reason == "exact_duplicate":
                    if debug:
                        debug.event("dedup_skip", scroll=scrolls, dedup_key=key,
                                    advertiser=ad.advertiser, domain=ad.displayed_domain,
                                    headline=ad.headline, creative_img=ad.creative_img)
                    continue
                if not decision.accepted and decision.reason == "lazy_media_duplicate":
                    if debug:
                        debug.event("lazy_media_duplicate_skip", scroll=scrolls,
                                    coarse_key=coarse_key,
                                    existing_keys=list(decision.related_keys),
                                    advertiser=ad.advertiser, domain=ad.displayed_domain,
                                    headline=ad.headline, creative_img=ad.creative_img,
                                    creative_area=creative_area)
                    continue
                for old_key in decision.removed_keys:
                    if debug:
                        debug.event("lazy_media_replaced", old_key=old_key,
                                    new_key=key, coarse_key=coarse_key)
                captured += 1
                debug_id = captured
                if debug and r.get("element_id"):
                    try:
                        html = feed_reader.card_html(r["element_id"])
                        debug.write_text(f"ads/{debug_id:04d}.html", html)
                    except Exception as exc:
                        debug.event("ad_dom_failed", debug_id=debug_id, error=repr(exc),
                                    element_id=r.get("element_id"))
                remaining_seconds = deadline - time.time()
                if shots and remaining_seconds > 8:
                    fn = shots_dir / f"{debug_id:04d}_{re.sub(r'[^a-z0-9]+','_', (ad.displayed_domain or ad.advertiser or 'ad').lower())[:24]}.png"
                    expect_media = bool(r.get("has_video")) or creative_area >= 45000
                    exact_screenshot = save_ad_screenshot(
                        page,
                        fn,
                        r.get("element_id"),
                        expect_media=expect_media,
                        interest_safe=interest_safe_mode,
                    )
                    if fn.exists():
                        ad.screenshot = str(fn.relative_to(run_dir))
                        if not exact_screenshot:
                            ad.screenshot_ok = False
                            ad.screenshot_issue = "viewport_fallback"
                        elif expect_media and _screenshot_has_blank_media(fn):
                            ad.screenshot_ok = False
                            ad.screenshot_issue = "blank_media"
                    if r.get("element_id"):
                        ad.has_video = ad.has_video or has_video_creative(page, r.get("element_id"))
                        if ad.has_video and ad.ad_type == "in_facebook":
                            ad.ad_type = "video"
                collection_service.accept(decision)
                if record_videos and ad.has_video and r.get("element_id") and not ad.video:
                    video_budget_seconds = min(float(video_max_seconds or 0), 45.0) + 20.0
                    if deadline - time.time() > video_budget_seconds:
                        fn = videos_dir / (
                            f"{debug_id:04d}_"
                            f"{re.sub(r'[^a-z0-9]+','_', (ad.displayed_domain or ad.advertiser or 'video').lower())[:24]}.mp4"
                        )
                        print(f"  recording video {fn.name}", flush=True)
                        video_play_attempts += 1
                        try:
                            with _hard_deadline(
                                video_budget_seconds,
                                f"video capture: {ad.displayed_domain or ad.advertiser}",
                            ):
                                ok, issue = record_ad_video(
                                    page,
                                    fn,
                                    r.get("element_id"),
                                    max_seconds=video_max_seconds,
                                    fps=video_fps,
                                    debug=debug,
                                    debug_id=debug_id,
                                )
                        except _OperationDeadlineExceeded as exc:
                            video_timeouts += 1
                            stop_reason = "video_timeout"
                            print(
                                f"  video timeout "
                                f"{ad.displayed_domain or ad.advertiser} after "
                                f"{video_budget_seconds:.0f}s; ending this cycle "
                                "with the captured ad saved",
                                flush=True,
                            )
                            if debug:
                                debug.event(
                                    "video_hard_timeout",
                                    debug_id=debug_id,
                                    domain=ad.displayed_domain,
                                    timeout_seconds=video_budget_seconds,
                                    error=str(exc),
                                )
                            _write_ads(run_dir / "ads.partial.json", ads)
                            break
                        if ok:
                            ad.video = str(fn.relative_to(run_dir))
                            print(f"  recorded video {fn.name}", flush=True)
                        else:
                            print(
                                f"  video record skipped {ad.displayed_domain or ad.advertiser}: {issue}",
                                flush=True,
                            )
                            if debug:
                                debug.event(
                                    "video_record_failed",
                                    debug_id=debug_id,
                                    advertiser=ad.advertiser,
                                    domain=ad.displayed_domain,
                                    issue=issue,
                                )
                    else:
                        issue = "time_budget"
                        print(
                            f"  video record skipped {ad.displayed_domain or ad.advertiser}: {issue}",
                            flush=True,
                        )
                        if debug:
                            debug.event(
                                "video_record_failed",
                                debug_id=debug_id,
                                advertiser=ad.advertiser,
                                domain=ad.displayed_domain,
                                issue=issue,
                            )
                # Persist before clicking: a broken landing must not lose the ad.
                _write_ads(run_dir / "ads.partial.json", ads)
                # inline click-resolve while this link ad is still in view
                resolve_budget_seconds = max(30.0, landing_archive_timeout * 2 + 15.0)
                if (
                    do_resolve
                    and ad.ad_type == "link"
                    and ad.displayed_domain
                    and resolved < resolve_max
                    and deadline - time.time() > resolve_budget_seconds
                ):
                    print(f"  resolving {ad.displayed_domain}", flush=True)
                    cta_click_attempts += 1
                    try:
                        with _hard_deadline(
                            resolve_budget_seconds,
                            f"landing resolve: {ad.displayed_domain}",
                        ):
                            resolve_in_view(
                                page,
                                ctx,
                                ad,
                                r.get("btn"),
                                r.get("element_id"),
                                run_dir,
                                debug=debug,
                                debug_id=debug_id,
                                feed_url=feed_url,
                                archive_landing=archive_landings,
                                landing_archive_timeout=landing_archive_timeout,
                                landing_archive_max_resources=(
                                    landing_archive_max_resources
                                ),
                            )
                    except _OperationDeadlineExceeded as exc:
                        resolve_timeouts += 1
                        print(
                            f"  resolve timeout {ad.displayed_domain} after "
                            f"{resolve_budget_seconds:.0f}s; ending this cycle "
                            "with the captured ad saved",
                            flush=True,
                        )
                        if debug:
                            debug.event(
                                "resolve_hard_timeout",
                                debug_id=debug_id,
                                domain=ad.displayed_domain,
                                timeout_seconds=resolve_budget_seconds,
                                error=str(exc),
                            )
                        stop_reason = "resolve_timeout"
                        break
                    if ad.landing_full:
                        if not collection_service.register_resolved(decision):
                            duplicate_fb_ad_ids += 1
                            if debug:
                                debug.event("duplicate_ad_id_skip", debug_id=debug_id,
                                            fb_ad_id=ad.fb_ad_id, domain=ad.displayed_domain)
                                debug.write_json(f"ads/{debug_id:04d}.json", {
                                    "raw": r, "parsed": asdict(ad), "dedup_key": key,
                                    "skipped": "duplicate_fb_ad_id",
                                })
                            print(f"  duplicate ad_id skipped {ad.displayed_domain} "
                                  f"(ad_id={ad.fb_ad_id})", flush=True)
                            _write_ads(run_dir / "ads.partial.json", ads)
                            continue
                        resolved += 1
                        print(f"  resolved {ad.displayed_domain} -> {ad.landing_clean} "
                              f"(ad_id={ad.fb_ad_id})", flush=True)
                # Resolving a permalink can navigate the feed page and replace
                # its DOM. Keep it after the CTA click so landing capture does
                # not depend on a stale element marker.
                if (
                    resolve_post_urls
                    and
                    not ad.facebook_post_url
                    and r.get("element_id")
                    and deadline - time.time() > 10
                ):
                    comment_open_attempts += 1
                    resolved_post = resolve_facebook_post_url(
                        page,
                        ad,
                        r.get("element_id"),
                        feed_url=feed_url,
                        debug=debug,
                        debug_id=debug_id,
                    )
                    if resolved_post:
                        print(
                            f"  saved Facebook post {ad.facebook_post_url}",
                            flush=True,
                        )
                if debug:
                    debug.write_json(f"ads/{debug_id:04d}.json", {
                        "raw": r, "parsed": asdict(ad), "dedup_key": key,
                    })
                _write_ads(run_dir / "ads.partial.json", ads)
                new_ads_in_view += 1
                last_ad_scroll = scrolls
                if max_ads_per_view > 0 and new_ads_in_view >= max_ads_per_view:
                    break
            if stop_reason:
                break
            # scroll + detect bottom
            actual_scroll_px = max(260, int(scroll_px * random.uniform(0.75, 1.35)))
            if debug:
                debug.event("scroll_start", scroll=scrolls + 1,
                            scroll_px=actual_scroll_px,
                            page_url=DebugRecorder._page_url(page), pages=len(ctx.pages))
            try:
                feed_reader.scroll(actual_scroll_px)
            except Exception as exc:
                print(f"[collect stop] scroll failed: {exc}", flush=True)
                stop_reason = "scroll_failed"
                break
            scrolls += 1
            time.sleep(random.uniform(1.9, 4.2))
            if scrolls >= next_long_pause_scroll:
                time.sleep(random.uniform(4.0, 8.0))
                next_long_pause_scroll = scrolls + random.randint(12, 18)
            if debug:
                debug.event("scroll", scroll=scrolls, elapsed=round(time.time() - t0, 3),
                            detected_rows=len(rows), unique_ads=len(ads),
                            resolved=resolved, refreshes=refreshes,
                            page_url=DebugRecorder._page_url(page), pages=len(ctx.pages))
            stale_feed = scrolls - last_ad_scroll >= 90
            periodic_refresh = scrolls > 0 and scrolls % 180 == 0
            if stale_feed or periodic_refresh:
                refreshes += 1
                if debug:
                    debug.event("refresh_start", scroll=scrolls, refreshes=refreshes,
                                reason="stale_feed" if stale_feed else "periodic",
                                page_url=DebugRecorder._page_url(page))
                    debug.screenshot(page, f"viewports/refresh_{scrolls:06d}.png")
                try:
                    _goto_with_retry(page, feed_url, timeout=15000, attempts=3)
                    if interest_safe_mode:
                        passive_media_guard_installed = (
                            install_passive_media_guard(page)
                            or passive_media_guard_installed
                        )
                    time.sleep(random.uniform(5.0, 9.0))
                except Exception:
                    pass
                last_ad_scroll = scrolls
            if scrolls <= 3 or scrolls % 10 == 0:
                if debug:
                    debug.screenshot(page, f"viewports/scroll_{scrolls:06d}.png")
                _write_ads(run_dir / "ads.partial.json", ads)
                print(f"[collect {int(time.time()-t0)}s scroll {scrolls}] "
                      f"unique ads={len(ads)} resolved={resolved} refreshes={refreshes}", flush=True)
    except KeyboardInterrupt:
        interrupted = True
        print(f"[collect interrupted] saving {len(ads)} ads", flush=True)
        if debug:
            debug.event("collect_interrupted", unique_ads=len(ads), resolved=resolved,
                        scrolls=scrolls, refreshes=refreshes)
    finally:
        _write_ads(run_dir / "ads.partial.json", ads)
    elapsed_seconds = round(time.time() - t0, 3)
    if not stop_reason:
        if interrupted or STOP_REQUESTED:
            stop_reason = "interrupted"
        elif scrolls >= max_scrolls:
            stop_reason = "scroll_budget"
        elif elapsed_seconds >= minutes * 60:
            stop_reason = "time_budget"
        else:
            stop_reason = "completed"
    passive_media_stats = (
        _passive_media_guard_stats(page)
        if interest_safe_mode
        else {
            "installed": False,
            "blocked_play_calls": 0,
            "pause_events": 0,
            "observed_videos": 0,
        }
    )
    passive_media_stats.update(passive_pre_navigation_guard)
    passive_media_stats["installed"] = bool(
        passive_media_stats["installed"] or passive_media_guard_installed
    )
    _write_json_atomic(run_dir / "summary.json", {
        "mode": "collect",
        "started_at": started_at,
        "finished_at": utc_now(),
        "requested_minutes": minutes,
        "elapsed_seconds": elapsed_seconds,
        "max_scrolls": max_scrolls,
        "scrolls": scrolls,
        "refreshes": refreshes,
        "resolve_enabled": do_resolve,
        "resolve_max": resolve_max,
        "scroll_px": scroll_px,
        "max_ads_per_view": max_ads_per_view,
        "feed_url": feed_url,
        "stop_reason": stop_reason,
        "facebook_login_required": facebook_login_required,
        "captured_candidates": captured,
        "duplicate_fb_ad_ids": duplicate_fb_ad_ids,
        "resolve_timeouts": resolve_timeouts,
        "video_timeouts": video_timeouts,
        "interest_safe_mode": interest_safe_mode,
        "interest_safe_overrides": interest_safe_overrides,
        "active_actions": {
            "cta_click_attempts": cta_click_attempts,
            "video_play_attempts": video_play_attempts,
            "comment_open_attempts": comment_open_attempts,
        },
        "passive_media_guard": passive_media_stats,
        **_ad_summary(ads),
    })
    print(f"[collect done] {len(ads)} unique ads, {resolved} resolved, "
          f"{scrolls} scrolls, {refreshes} refreshes")
    if debug:
        debug.event("collect_finished", unique_ads=len(ads), resolved=resolved,
                    scrolls=scrolls, refreshes=refreshes)
        _write_ads(run_dir / "ads.partial.json", ads)
    return ads


# ── main ──────────────────────────────────────────────────────────────────
def main(argv: Sequence[str] | None = None) -> int:
    global OCTO_API
    global OCTO_HEADLESS
    global OCTO_PROFILE_UUID

    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--minutes", type=float, default=10.0,
                    help="Collection budget in minutes (default 10).")
    ap.add_argument("--collect-scrolls", type=int, default=10000,
                    help="Hard cap on feed scrolls.")
    ap.add_argument("--resolve-max", type=int, default=200,
                    help="Max link-ads to click-resolve for the full URL.")
    ap.add_argument("--scroll-px", type=int, default=520,
                    help="Mouse-wheel pixels per feed step; lower means more overlap (default 520).")
    ap.add_argument("--max-ads-per-view", type=int, default=1,
                    help="Max newly captured ads to process before scrolling again (default 1).")
    ap.add_argument("--no-resolve", action="store_true",
                    help="Collect only, never click (no full landing URLs).")
    ap.add_argument(
        "--passive-collect",
        action="store_true",
        help=(
            "Interest-safe scan: never click CTAs/comments or start videos. "
            "Relevant ads can be enriched in a separate post-classification step."
        ),
    )
    ap.add_argument("--no-shots", action="store_true",
                    help="Skip per-ad screenshots.")
    ap.add_argument("--no-video-recording", action="store_true",
                    help="Do not record detected video creatives.")
    ap.add_argument("--video-max-seconds", type=float, default=30.0,
                    help="Maximum seconds to record per video creative (hard-capped at 45).")
    ap.add_argument("--video-fps", type=int, default=8,
                    help="Frame rate for recorded video creatives (default 8).")
    ap.add_argument("--no-landing-archives", action="store_true",
                    help="Do not save zip archives of resolved landing pages.")
    ap.add_argument("--landing-archive-timeout", type=float, default=20.0,
                    help="HTTP timeout for landing archive fetches (default 20s).")
    ap.add_argument("--landing-archive-max-resources", type=int, default=120,
                    help="Maximum linked resources per landing archive.")
    ap.add_argument("--debug", action="store_true",
                    help="Save maximum debug artifacts: trace, events, DOM, viewports, resolve shots.")
    ap.add_argument("--out", default="fb_spy/results",
                    help="Output directory root.")
    ap.add_argument("--run-dir", default="",
                    help="Exact output directory for this run. Overrides --out.")
    ap.add_argument("--octo-host", default="127.0.0.1",
                    help="Octo Browser Local API host (default 127.0.0.1).")
    ap.add_argument("--octo-port", type=int, default=58888,
                    help="Octo Browser Local API port (default 58888).")
    ap.add_argument("--octo-profile-uuid", default=OCTO_PROFILE_UUID,
                    help="Octo Browser profile UUID to start/use.")
    ap.add_argument("--octo-headless", action="store_true",
                    help="Start Octo browser profiles without a visible window.")
    ap.add_argument("--topic", default="",
                    help="Optional Facebook mobile search topic to scroll instead of the home feed.")
    args = ap.parse_args(argv)

    signal.signal(signal.SIGINT, _request_stop)
    signal.signal(signal.SIGTERM, _request_stop)

    OCTO_API = f"http://{args.octo_host}:{args.octo_port}"
    OCTO_PROFILE_UUID = args.octo_profile_uuid
    OCTO_HEADLESS = args.octo_headless
    feed_url = "https://m.facebook.com/"
    if args.topic.strip():
        feed_url = f"https://m.facebook.com/search/top/?q={quote_plus(args.topic.strip())}"

    if args.run_dir.strip():
        run_dir = Path(args.run_dir)
    else:
        run_dir = Path(args.out) / datetime.now().strftime("run_%Y%m%d_%H%M%S")
    run_dir.mkdir(parents=True, exist_ok=True)
    debug = DebugRecorder(run_dir, args.debug, clock=utc_now)
    runner_started_at = utc_now()
    runner_started_monotonic = time.monotonic()
    try:
        ws, conn = get_cdp_endpoint()
        ws = rewrite_cdp_endpoint_host(ws, args.octo_host)
        profile_country = normalize_country(conn.get("country"))
        print(f"[octo] CDP {ws}  ip={conn.get('ip')} country={profile_country}")
        _write_run_meta(run_dir, {
            "collector_metric_version": COLLECTOR_METRIC_VERSION,
            "octo_profile_uuid": args.octo_profile_uuid,
            "octo_host": args.octo_host,
            "octo_port": args.octo_port,
            "octo_headless": args.octo_headless,
            "octo_ip": conn.get("ip"),
            "profile_country": profile_country,
            "connection_data": conn,
            "started_at": runner_started_at,
        })
        debug.event("octo_connected", ws=ws, connection=conn)

        with sync_playwright() as p:
            b = p.chromium.connect_over_cdp(ws)
            ctx = b.contexts[0]
            debug.attach_context(ctx)
            page = None
            if not args.topic.strip():
                page = next((pg for pg in ctx.pages if _is_fb_feed_url(pg.url)), None)
            if page is None:
                page = ctx.new_page()
            interrupted = False
            try:
                ads = collect(page, ctx, run_dir, minutes=args.minutes,
                              max_scrolls=args.collect_scrolls, shots=not args.no_shots,
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
                                  not args.no_video_recording
                                  and not args.passive_collect
                              ),
                              video_max_seconds=args.video_max_seconds,
                              video_fps=args.video_fps,
                              max_ads_per_view=args.max_ads_per_view,
                              resolve_post_urls=not args.passive_collect,
                              interest_safe_mode=args.passive_collect)
                out = run_dir / "ads.json"
                _write_ads(out, ads)
                if args.passive_collect:
                    neutralize_profile_pages(page, ctx)
                _fast_exit_after_browser_operation_timeout(run_dir)
            except BaseException as exc:
                interrupted = isinstance(exc, KeyboardInterrupt)
                debug.event("fatal", error=repr(exc), traceback=traceback.format_exc(),
                            page_url=DebugRecorder._page_url(page),
                            pages=[DebugRecorder._page_url(pg) for pg in ctx.pages])
                if not interrupted:
                    debug.screenshot(page, "errors/fatal.png")
                raise
            finally:
                if interrupted or STOP_REQUESTED:
                    debug.event("debug_cleanup_skipped", reason="keyboard_interrupt")
                else:
                    debug.finish_context(ctx)
                    debug.event(
                        "browser_left_active_for_followup",
                        passive_collect=args.passive_collect,
                        page_url=DebugRecorder._page_url(page),
                    )

        n = len(ads)
        by_type: dict[str, int] = {}
        resolved = 0
        for a in ads.values():
            by_type[a.ad_type] = by_type.get(a.ad_type, 0) + 1
            if a.landing_full:
                resolved += 1
        print("\n=== DONE ===")
        print(f"unique ads: {n}  by_type: {by_type}")
        print(f"full landing resolved: {resolved}")
        print(f"results: {run_dir}/ads.json")
        if args.debug:
            print(f"debug: {run_dir}/debug/")
        return 0
    except OctoApiError as exc:
        reason = _write_octo_start_failure(
            run_dir,
            profile_uuid=args.octo_profile_uuid,
            octo_host=args.octo_host,
            octo_port=args.octo_port,
            octo_headless=args.octo_headless,
            requested_minutes=args.minutes,
            started_at=runner_started_at,
            elapsed_seconds=time.monotonic() - runner_started_monotonic,
            error=exc,
        )
        debug.event("main_failed", error=repr(exc))
        print(f"[octo error:{reason}] {exc}", file=sys.stderr, flush=True)
        if args.debug:
            print(f"debug: {run_dir}/debug/", file=sys.stderr, flush=True)
        return 2
    except BaseException as exc:
        debug.event("main_failed", error=repr(exc), traceback=traceback.format_exc())
        raise
    finally:
        debug.close()


if __name__ == "__main__":
    raise SystemExit(main())

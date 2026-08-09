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

import os
import random
import re
import time
import traceback
from dataclasses import asdict
from pathlib import Path

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
from app.facebook.collection import commands as collection_commands
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
from app.facebook.collection.cli import artifacts as collection_artifacts
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
BROWSER_OPERATION_TIMEOUT_REASONS = (
    collection_artifacts.BROWSER_OPERATION_TIMEOUT_REASONS
)
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


_write_ads = collection_artifacts.write_ads
_write_json_atomic = collection_artifacts.write_json_atomic
_write_text_atomic = collection_artifacts.write_text_atomic
_write_run_meta = collection_artifacts.write_run_meta
_fast_exit_after_browser_operation_timeout = (
    collection_artifacts.fast_exit_after_browser_operation_timeout
)
_octo_start_failure_reason = collection_artifacts.octo_start_failure_reason
_write_octo_start_failure = collection_artifacts.write_octo_start_failure


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
main = collection_commands.main

if __name__ == "__main__":
    raise SystemExit(main())

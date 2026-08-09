"""Legacy collection entrypoint and Octo compatibility facade."""

from __future__ import annotations

import time

from app.browser import BrowserOperationDeadlineExceeded, hard_deadline
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
    CollectedAd as Ad,
)
from app.facebook.collection import (
    ad_summary,
    creative_identity,
    is_lazy_video_image,
    normalize_fingerprint_text,
)
from app.facebook.collection import commands as collection_commands
from app.facebook.collection import stop as collection_stop
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
_OperationDeadlineExceeded = BrowserOperationDeadlineExceeded
_hard_deadline = hard_deadline
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
DebugRecorder = collection_playwright.DebugRecorder
install_passive_media_guard = collection_playwright.install_passive_media_guard
prepare_passive_media_guard = collection_playwright.prepare_passive_media_guard
_passive_media_guard_stats = collection_playwright.passive_media_guard_stats
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
    collection_stop.request_stop(signum, _frame)


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
collect = collection_playwright.collect_feed

# ── main ──────────────────────────────────────────────────────────────────
main = collection_commands.main

if __name__ == "__main__":
    raise SystemExit(main())

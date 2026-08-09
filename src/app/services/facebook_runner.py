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
import base64
import json
import os
import random
import re
import shutil
import signal
import subprocess
import sys
import time
import traceback
from collections.abc import Sequence
from dataclasses import asdict
from datetime import datetime
from io import BytesIO
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
from app.facebook.collection.adapters.playwright import (
    pause_all_videos as _pause_all_videos,
)
from app.facebook.enrichment.landing.adapters import (
    playwright as landing_playwright,
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


MEDIA_READY_JS = r"""
(elementId) => {
  const root = document.querySelector(`[data-fbspy-id="${elementId}"]`);
  if (!root) return false;
  const visible = el => {
    const r = el.getBoundingClientRect();
    const s = getComputedStyle(el);
    return r.width * r.height >= 25000 &&
      r.bottom > 0 && r.top < innerHeight &&
      s.display !== "none" && s.visibility !== "hidden" && Number(s.opacity || 1) > 0.05;
  };
  const media = [...root.querySelectorAll("img,video")].filter(visible);
  if (!media.length) return true;
  return media.some(el => {
    if (el.tagName === "IMG") {
      return el.complete && el.naturalWidth > 50 && el.naturalHeight > 50;
    }
    if (el.tagName === "VIDEO") {
      return (el.readyState || 0) >= 2 ||
        (el.videoWidth > 50 && el.videoHeight > 50) ||
        !!el.poster;
    }
    return false;
  });
}
"""


VIDEO_CREATIVE_JS = r"""
(elementId) => {
  const root = document.querySelector(`[data-fbspy-id="${elementId}"]`);
  if (!root) return false;
  if (root.querySelector("video")) return true;
  for (const el of root.querySelectorAll('button,[role="button"],[aria-label],video')) {
    const cls = (typeof el.className === "string" ? el.className : "").toLowerCase();
    const label = (el.getAttribute("aria-label") || "").toLowerCase();
    if (cls.includes("inline-video-icon") || label.includes("video")) return true;
  }
  return false;
}
"""


VIDEO_PREP_JS = r"""
async (elementId) => {
  const root = document.querySelector(`[data-fbspy-id="${elementId}"]`);
  if (!root) return {ok:false, reason:"missing_root"};
  root.scrollIntoView({block:"center", inline:"nearest"});
  await new Promise(resolve => setTimeout(resolve, 300));
  const visible = el => {
    const r = el.getBoundingClientRect();
    const s = getComputedStyle(el);
    return r.width * r.height >= 25000 &&
      r.bottom > 0 && r.top < innerHeight &&
      s.display !== "none" && s.visibility !== "hidden" &&
      Number(s.opacity || 1) > 0.05;
  };
  const videos = [...root.querySelectorAll("video")]
    .filter(visible)
    .map(video => {
      const r = video.getBoundingClientRect();
      return {video, area:r.width*r.height, rect:r};
    })
    .sort((a,b) => b.area - a.area);
  if (!videos.length) return {ok:false, reason:"missing_visible_video"};
  const {video, rect} = videos[0];
  try { video.muted = true; } catch {}
  try { video.playsInline = true; } catch {}
  try {
    if (Number.isFinite(video.currentTime) && video.currentTime > 0.05) {
      video.pause();
      video.currentTime = 0;
      await Promise.race([
        new Promise(resolve => video.addEventListener("seeked", resolve, {once:true})),
        new Promise(resolve => setTimeout(resolve, 600)),
      ]);
    }
  } catch {}
  let played = false;
  let error = "";
  try {
    await video.play();
    played = true;
  } catch (exc) {
    error = String((exc && exc.message) || exc || "");
  }
  return {
    ok:true,
    played,
    error,
    paused:video.paused,
    ended:video.ended,
    currentTime:Number.isFinite(video.currentTime) ? video.currentTime : null,
    duration:Number.isFinite(video.duration) ? video.duration : null,
    x:Math.round(rect.left + rect.width / 2),
    y:Math.round(rect.top + rect.height / 2),
    width:Math.round(rect.width),
    height:Math.round(rect.height),
  };
}
"""


def _screenshot_has_blank_media(path: Path) -> bool:
    """Best-effort screenshot QA: detect a large blank media placeholder."""
    try:
        from PIL import Image
    except Exception:
        return False
    try:
        im = Image.open(path).convert("RGB")
    except Exception:
        return False
    w, h = im.size
    if w < 280 or h < 420:
        return False

    x0, x1 = int(w * 0.04), int(w * 0.96)
    y0 = max(80, int(h * 0.08))
    y1 = h - max(150, int(h * 0.18))
    if y1 - y0 < 180:
        return False

    crop = im.crop((x0, y0, x1, y1))
    sample_h = max(1, round(crop.height * 96 / max(1, crop.width)))
    content_sample = crop.resize((96, sample_h))
    content_pixels = (
        content_sample.get_flattened_data()
        if hasattr(content_sample, "get_flattened_data")
        else content_sample.getdata()
    )
    total = saturated = 0
    for r, g, b in content_pixels:
        total += 1
        avg = (r + g + b) / 3
        if max(r, g, b) - min(r, g, b) > 50 and avg < 245:
            saturated += 1
    if total and saturated / total > 0.015:
        return False

    run = max_run = 0
    step = 16
    for y in range(y0, y1, step):
        band = im.crop((x0, y, x1, min(y + step, y1)))
        sample_h = max(1, round(band.height * 64 / max(1, band.width)))
        sample = band.resize((64, sample_h))
        pixels = sample.get_flattened_data() if hasattr(sample, "get_flattened_data") else sample.getdata()
        total = 0
        light_neutral = dark = 0
        for r, g, b in pixels:
            total += 1
            avg = (r + g + b) / 3
            if (avg > 232 and max(r, g, b) - min(r, g, b) < 25) or (r > 245 and g > 245 and b > 245):
                light_neutral += 1
            if avg < 120:
                dark += 1
        if total and light_neutral / total > 0.965 and dark / total < 0.003:
            run += band.height
        else:
            max_run = max(max_run, run)
            run = 0
    max_run = max(max_run, run)
    return max_run >= min(360, max(220, int(h * 0.32)))


def save_ad_screenshot(
    page,
    path: Path,
    element_id: str | None,
    expect_media: bool = False,
    *,
    interest_safe: bool = False,
) -> bool:
    """Screenshot the exact detected ad element; fall back to viewport only if lost."""
    if element_id:
        loc = page.locator(f'[data-fbspy-id="{element_id}"]').first
        attempts = 1 if interest_safe else (2 if expect_media else 1)
        for attempt in range(attempts):
            try:
                loc.scroll_into_view_if_needed(timeout=5000)
                if interest_safe:
                    _pause_all_videos(page)
                try:
                    page.wait_for_function(
                        MEDIA_READY_JS,
                        arg=element_id,
                        timeout=(
                            1200
                            if interest_safe
                            else 3000 + attempt * 2000
                        ),
                    )
                except Exception:
                    pass
                time.sleep(0.15 if interest_safe else 0.5 + attempt * 1.0)
                box = loc.bounding_box(timeout=5000)
                if box and box.get("height", 0) <= 2600 and box.get("width", 0) <= 1200:
                    loc.screenshot(path=str(path), timeout=10000)
                    if expect_media and attempt == 0 and _screenshot_has_blank_media(path):
                        print(f"  screenshot retry blank media {path.name}", flush=True)
                        continue
                    return True
            except Exception:
                pass
    try:
        page.screenshot(path=str(path))
        return False
    except Exception:
        return False


def has_video_creative(page, element_id: str | None) -> bool:
    if not element_id:
        return False
    try:
        return bool(page.evaluate(VIDEO_CREATIVE_JS, element_id))
    except Exception:
        return False


def record_ad_video(
    page,
    path: Path,
    element_id: str | None,
    *,
    max_seconds: float = 30.0,
    fps: int = 8,
    debug: DebugRecorder | None = None,
    debug_id: int = 0,
) -> tuple[bool, str]:
    """Record the visible ad block as MP4 frames.

    CDP access to an existing Octo profile cannot enable Playwright's native
    context video recorder, and Facebook video src values are often blob-backed.
    Chrome's screencast stream is used instead of repeated screenshot commands:
    captureScreenshot can wedge indefinitely on some animated Facebook posts.
    The viewport frames are cropped to the exact ad and encoded with ffmpeg.
    The result is visual-only by design.
    """
    if not element_id:
        return False, "missing_element_id"
    ffmpeg = shutil.which("ffmpeg")
    if not ffmpeg:
        return False, "ffmpeg_not_found"

    fps = max(1, min(int(fps or 8), 20))
    max_seconds = max(1.0, min(float(max_seconds or 30.0), 45.0))
    loc = page.locator(f'[data-fbspy-id="{element_id}"]').first

    try:
        loc.scroll_into_view_if_needed(timeout=5000)
    except Exception:
        return False, "element_not_visible"

    prep = _prepare_video_playback(page, element_id)
    if not prep.get("ok"):
        return False, str(prep.get("reason") or "video_prepare_failed")
    if not prep.get("played"):
        try:
            page.mouse.click(int(prep.get("x") or 0), int(prep.get("y") or 0))
            time.sleep(0.5)
        except Exception:
            pass
        prep = _prepare_video_playback(page, element_id)

    duration = prep.get("duration")
    if isinstance(duration, (int, float)) and duration > 0:
        record_seconds = min(max_seconds, max(1.5, float(duration)))
    else:
        record_seconds = max_seconds

    clip = _element_viewport_clip(page, element_id)
    if clip is None:
        return False, "element_clip_unavailable"

    path.parent.mkdir(parents=True, exist_ok=True)
    frames_dir = path.with_suffix(path.suffix + ".frames")
    if frames_dir.exists():
        shutil.rmtree(frames_dir, ignore_errors=True)
    frames_dir.mkdir(parents=True, exist_ok=True)

    started = time.monotonic()
    min_frames = max(2, min(fps * 2, 12))
    try:
        frame_count, last_error = _capture_screencast_frames(
            page,
            frames_dir,
            clip=clip,
            record_seconds=record_seconds,
            fps=fps,
        )
        captured_frame_count = frame_count
        capture_elapsed = max(0.1, time.monotonic() - started)
        encode_fps = max(1.0, min(float(fps), captured_frame_count / capture_elapsed))
        trimmed_frames = 0
        if frame_count >= 2:
            trimmed_frame_count = _trim_static_tail_frames(
                frames_dir,
                frame_count=frame_count,
                fps=fps,
                min_frames=min_frames,
            )
            trimmed_frames = frame_count - trimmed_frame_count
            frame_count = trimmed_frame_count

        if frame_count < 2:
            return False, last_error or "too_few_frames"
        ok, message = _encode_video_frames(frames_dir, path, fps=encode_fps, ffmpeg=ffmpeg)
        if ok and debug:
            debug.event(
                "video_recorded",
                debug_id=debug_id,
                path=str(path),
                frames=frame_count,
                fps=fps,
                encode_fps=round(encode_fps, 3),
                capture_seconds=round(capture_elapsed, 3),
                max_seconds=max_seconds,
                clip=clip,
                trimmed_frames=trimmed_frames,
                source_duration=duration,
            )
        return ok, message
    finally:
        _pause_ad_video(page, element_id)
        shutil.rmtree(frames_dir, ignore_errors=True)


def _pause_ad_video(page, element_id: str | None) -> None:
    if not element_id:
        return
    try:
        page.evaluate(
            """
            elementId => {
              const root = document.querySelector(
                `[data-fbspy-id="${elementId}"]`
              );
              if (!root) return;
              for (const video of root.querySelectorAll("video")) {
                try { video.pause(); } catch (_) {}
              }
            }
            """,
            element_id,
        )
    except Exception:
        pass


def _capture_screencast_frames(
    page,
    frames_dir: Path,
    *,
    clip: dict[str, float],
    record_seconds: float,
    fps: int,
) -> tuple[int, str]:
    """Collect compositor frames without issuing Page.captureScreenshot."""
    client = None
    started_stream = False
    interval = 1.0 / max(1, fps)
    state = {
        "accepting": True,
        "frame_count": 0,
        "next_frame_at": time.monotonic(),
        "last_error": "",
    }

    def on_frame(event: dict) -> None:
        try:
            client.send(
                "Page.screencastFrameAck",
                {"sessionId": event["sessionId"]},
            )
        except Exception as exc:
            state["last_error"] = repr(exc)
            return
        if not state["accepting"]:
            return

        now = time.monotonic()
        if now < state["next_frame_at"]:
            return
        frame_number = int(state["frame_count"]) + 1
        frame_path = frames_dir / f"frame_{frame_number:05d}.png"
        ok, issue = _write_screencast_frame(
            str(event.get("data") or ""),
            frame_path,
            clip=clip,
        )
        if not ok:
            state["last_error"] = issue
            return
        state["frame_count"] = frame_number
        next_frame_at = float(state["next_frame_at"]) + interval
        state["next_frame_at"] = max(next_frame_at, now + interval * 0.5)

    try:
        client = page.context.new_cdp_session(page)
        client.on("Page.screencastFrame", on_frame)
        client.send(
            "Page.startScreencast",
            {
                "format": "jpeg",
                "quality": 80,
                "everyNthFrame": 1,
            },
        )
        started_stream = True
        page.wait_for_timeout(round(max(0.1, record_seconds) * 1000))
    except Exception as exc:
        state["last_error"] = repr(exc)
    finally:
        state["accepting"] = False
        if client is not None:
            if started_stream:
                try:
                    client.send("Page.stopScreencast")
                except Exception as exc:
                    if not state["last_error"]:
                        state["last_error"] = repr(exc)
            try:
                client.detach()
            except Exception:
                pass
    return int(state["frame_count"]), str(state["last_error"])


def _write_screencast_frame(
    encoded_frame: str,
    path: Path,
    *,
    clip: dict[str, float],
) -> tuple[bool, str]:
    try:
        from PIL import Image

        payload = base64.b64decode(encoded_frame, validate=True)
        with Image.open(BytesIO(payload)) as source:
            image = source.convert("RGB")
            viewport_width = max(
                1.0,
                float(clip.get("viewport_width") or image.width),
            )
            viewport_height = max(
                1.0,
                float(clip.get("viewport_height") or image.height),
            )
            scale_x = image.width / viewport_width
            scale_y = image.height / viewport_height
            left = max(0, round(float(clip["x"]) * scale_x))
            top = max(0, round(float(clip["y"]) * scale_y))
            right = min(
                image.width,
                round((float(clip["x"]) + float(clip["width"])) * scale_x),
            )
            bottom = min(
                image.height,
                round((float(clip["y"]) + float(clip["height"])) * scale_y),
            )
            if right - left < 40 or bottom - top < 40:
                return False, "screencast_clip_too_small"
            image.crop((left, top, right, bottom)).save(path, format="PNG")
        return True, "ok"
    except Exception as exc:
        return False, repr(exc)


def _prepare_video_playback(page, element_id: str) -> dict:
    try:
        data = page.evaluate(VIDEO_PREP_JS, element_id)
        return data if isinstance(data, dict) else {"ok": False, "reason": "bad_video_prep"}
    except Exception as exc:
        return {"ok": False, "reason": repr(exc)}


def _element_viewport_clip(page, element_id: str) -> dict[str, float] | None:
    try:
        clip = page.evaluate(
            r"""
            (elementId) => {
              const root = document.querySelector(`[data-fbspy-id="${elementId}"]`);
              if (!root) return null;
              const r = root.getBoundingClientRect();
              const x = Math.max(0, Math.floor(r.left));
              const y = Math.max(0, Math.floor(r.top));
              const right = Math.min(window.innerWidth, Math.ceil(r.right));
              const bottom = Math.min(window.innerHeight, Math.ceil(r.bottom));
              const width = right - x;
              const height = bottom - y;
              if (width < 40 || height < 40) return null;
              return {
                x,
                y,
                width,
                height,
                viewport_width: window.innerWidth,
                viewport_height: window.innerHeight,
              };
            }
            """,
            element_id,
        )
    except Exception:
        return None
    if not isinstance(clip, dict):
        return None
    try:
        x = float(clip["x"])
        y = float(clip["y"])
        width = float(clip["width"])
        height = float(clip["height"])
    except Exception:
        return None
    if width < 40 or height < 40:
        return None
    result = {"x": x, "y": y, "width": width, "height": height}
    for key in ("viewport_width", "viewport_height"):
        try:
            value = float(clip[key])
        except Exception:
            continue
        if value > 0:
            result[key] = value
    return result


def _trim_static_tail_frames(
    frames_dir: Path,
    *,
    frame_count: int,
    fps: int,
    min_frames: int,
) -> int:
    """Drop long duplicated tails caused by short/ended videos staying on the last frame."""
    if frame_count <= min_frames + fps * 2:
        return frame_count
    try:
        from PIL import Image, ImageChops, ImageStat
    except Exception:
        return frame_count

    def signature(path: Path):
        with Image.open(path) as image:
            resampling = getattr(Image, "Resampling", Image).BILINEAR
            return image.convert("L").resize((64, 64), resampling)

    def diff_score(left, right) -> float:
        stat = ImageStat.Stat(ImageChops.difference(left, right))
        return float(stat.mean[0])

    last_motion_frame = 1
    previous = None
    threshold = 0.45
    try:
        for index in range(1, frame_count + 1):
            current = signature(frames_dir / f"frame_{index:05d}.png")
            if previous is not None and diff_score(previous, current) > threshold:
                last_motion_frame = index
            previous = current
    except Exception:
        return frame_count

    tail_grace = max(fps, min_frames)
    min_keep_frames = max(min_frames, fps * 3)
    keep_frames = max(min_keep_frames, min(frame_count, last_motion_frame + tail_grace))
    if frame_count - keep_frames < fps * 2:
        return frame_count
    for index in range(keep_frames + 1, frame_count + 1):
        try:
            (frames_dir / f"frame_{index:05d}.png").unlink()
        except FileNotFoundError:
            pass
    return keep_frames


def _encode_video_frames(
    frames_dir: Path,
    output_path: Path,
    *,
    fps: float,
    ffmpeg: str,
) -> tuple[bool, str]:
    tmp_path = output_path.with_suffix(output_path.suffix + ".tmp.mp4")
    fps_arg = f"{max(1.0, float(fps)):.3f}".rstrip("0").rstrip(".")
    cmd = [
        ffmpeg,
        "-y",
        "-hide_banner",
        "-loglevel",
        "error",
        "-framerate",
        fps_arg,
        "-start_number",
        "1",
        "-i",
        str(frames_dir / "frame_%05d.png"),
        "-vf",
        "scale=trunc(iw/2)*2:trunc(ih/2)*2",
        "-c:v",
        "libx264",
        "-preset",
        "veryfast",
        "-crf",
        "23",
        "-pix_fmt",
        "yuv420p",
        "-movflags",
        "+faststart",
        str(tmp_path),
    ]
    try:
        completed = subprocess.run(
            cmd,
            check=False,
            capture_output=True,
            text=True,
            timeout=90,
        )
    except Exception as exc:
        return False, repr(exc)
    if completed.returncode != 0:
        return False, (completed.stderr or completed.stdout or "ffmpeg_failed")[-1000:]
    tmp_path.replace(output_path)
    return output_path.exists() and output_path.stat().st_size > 0, "ok"


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

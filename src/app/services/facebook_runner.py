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
from contextlib import contextmanager
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from io import BytesIO
from pathlib import Path
from urllib.parse import quote_plus

from playwright.sync_api import TimeoutError as PlaywrightTimeoutError
from playwright.sync_api import sync_playwright

from app.facebook.adapters.octo import (
    OctoHttpClient,
    OctoProfileSessionManager,
)
from app.facebook.adapters.octo import (
    rewrite_cdp_endpoint_host as _rewrite_cdp_endpoint_host,
)
from app.facebook.enrichment import (
    archive_landing_page_from_browser,
    save_landing_screenshot_from_browser,
    wait_for_landing_page_ready,
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
TRANSIENT_NAVIGATION_ERRORS = (
    "ERR_SOCKS_CONNECTION_FAILED",
    "ERR_PROXY_CONNECTION_FAILED",
    "ERR_NETWORK_CHANGED",
    "ERR_CONNECTION_RESET",
    "ERR_CONNECTION_CLOSED",
    "ERR_TIMED_OUT",
)
PROXY_CERTIFICATE_AUTHORITY_ERROR = "ERR_CERT_AUTHORITY_INVALID"
BROWSER_OPERATION_TIMEOUT_REASONS = frozenset({
    "resolve_timeout",
    "video_timeout",
})

# Sponsored marker glyphs (private use area). Language-independent.
GLYPHS = [0xF17E1, 0xF078B]

# Domains that appear inside ad cards but are NOT the advertiser landing.
BAD_DOMAINS = (
    "google.com", "facebook.com", "fb.com", "fb.me", "youtube.com",
    "instagram.com", "wa.me", "whatsapp.com", "messenger.com",
)


def utc_now() -> str:
    return datetime.now(UTC).isoformat()


def _norm_fingerprint_text(value: str) -> str:
    return re.sub(r"\s+", " ", value or "").strip().casefold()


def _creative_identity(url: str) -> str:
    if not url:
        return ""
    try:
        from urllib.parse import urlsplit
        p = urlsplit(url)
        return f"{p.netloc.lower()}{p.path}"
    except Exception:
        return url.split("?", 1)[0]


def _is_lazy_video_image(url: str, *, has_video: bool, creative_area: int) -> bool:
    """Detect a profile thumbnail accidentally selected for a large video."""
    if not has_video or creative_area < 45000 or not url:
        return False
    match = re.search(r"(?:^|[_=&])p(\d{2,4})x(\d{2,4})(?:[_&]|$)", url)
    return bool(match and max(int(match.group(1)), int(match.group(2))) <= 240)


def _request_stop(signum, _frame) -> None:
    global STOP_REQUESTED
    STOP_REQUESTED = True
    raise KeyboardInterrupt(f"signal {signum}")


class _OperationDeadlineExceeded(BaseException):
    pass


@contextmanager
def _hard_deadline(seconds: float, label: str):
    """Interrupt a blocking sync browser call on Unix without stopping the run."""
    if seconds <= 0 or not hasattr(signal, "SIGALRM"):
        yield
        return

    previous_handler = signal.getsignal(signal.SIGALRM)
    previous_timer = signal.setitimer(signal.ITIMER_REAL, 0)
    started = time.monotonic()

    def expire(_signum, _frame) -> None:
        raise _OperationDeadlineExceeded(label)

    signal.signal(signal.SIGALRM, expire)
    signal.setitimer(signal.ITIMER_REAL, seconds)
    try:
        yield
    finally:
        signal.setitimer(signal.ITIMER_REAL, 0)
        signal.signal(signal.SIGALRM, previous_handler)
        remaining, interval = previous_timer
        if remaining > 0:
            elapsed = time.monotonic() - started
            signal.setitimer(
                signal.ITIMER_REAL,
                max(1e-6, remaining - elapsed),
                interval,
            )


class _TeeStream:
    def __init__(self, *streams):
        self.streams = streams

    def write(self, data):
        for stream in self.streams:
            stream.write(data)
        return len(data)

    def flush(self):
        for stream in self.streams:
            stream.flush()

    def isatty(self):
        return any(getattr(stream, "isatty", lambda: False)() for stream in self.streams)


class DebugRecorder:
    def __init__(self, run_dir: Path, enabled: bool):
        self.enabled = enabled
        self.root = run_dir / "debug"
        self._events = None
        self._run_log = None
        self._stdout = None
        self._stderr = None
        self._attached_pages: set[int] = set()
        self._event_counts: dict[str, int] = {}
        if not enabled:
            return
        for name in ("ads", "errors", "resolve", "viewports"):
            (self.root / name).mkdir(parents=True, exist_ok=True)
        self._events = (self.root / "events.jsonl").open("a", encoding="utf-8", buffering=1)
        self._run_log = (self.root / "run.log").open("a", encoding="utf-8", buffering=1)
        self._stdout, self._stderr = sys.stdout, sys.stderr
        sys.stdout = _TeeStream(sys.stdout, self._run_log)
        sys.stderr = _TeeStream(sys.stderr, self._run_log)
        self.event("debug_started")

    def event(self, kind: str, **data) -> None:
        if not self.enabled or not self._events:
            return
        payload = self._compact({"at": utc_now(), "kind": kind, **data})
        try:
            self._events.write(json.dumps(payload, ensure_ascii=False, default=str) + "\n")
        except Exception:
            pass

    @classmethod
    def _compact(cls, value):
        if isinstance(value, str):
            return value if len(value) <= 1600 else value[:1600] + "...<truncated>"
        if isinstance(value, dict):
            return {str(k): cls._compact(v) for k, v in value.items()}
        if isinstance(value, (list, tuple)):
            return [cls._compact(v) for v in value[:100]]
        return value

    def limited_event(self, group: str, limit: int, kind: str, **data) -> None:
        count = self._event_counts.get(group, 0) + 1
        self._event_counts[group] = count
        if count <= limit:
            self.event(kind, **data)
        elif count == limit + 1:
            self.event("events_suppressed", group=group, limit=limit)

    def attach_context(self, ctx) -> None:
        if not self.enabled:
            return
        try:
            ctx.tracing.start(screenshots=True, snapshots=True, sources=True)
            self.event("trace_started")
        except Exception as exc:
            self.event("trace_start_failed", error=repr(exc))
        for page in list(ctx.pages):
            self.attach_page(page)
        ctx.on("page", self.attach_page)

    def attach_page(self, page) -> None:
        if not self.enabled or id(page) in self._attached_pages:
            return
        self._attached_pages.add(id(page))
        self.event("page_attached", url=self._page_url(page))
        page.on("console", lambda msg: self.limited_event("console", 120,
            "console", level=msg.type, text=msg.text, page_url=self._page_url(page)))
        page.on("pageerror", lambda exc: self.event(
            "page_error", error=repr(exc), page_url=self._page_url(page)))
        page.on("requestfailed", lambda req: self.limited_event("network", 160,
            "request_failed", method=req.method, url=req.url,
            failure=req.failure, page_url=self._page_url(page)))
        page.on("response", lambda resp: self._record_bad_response(page, resp))

    def _record_bad_response(self, page, response) -> None:
        try:
            if response.status >= 400:
                self.limited_event("network", 160, "http_error", status=response.status,
                                   method=response.request.method, url=response.url,
                                   page_url=self._page_url(page))
        except Exception:
            pass

    @staticmethod
    def _page_url(page) -> str:
        try:
            return page.url
        except Exception:
            return ""

    def screenshot(self, page, relative: str, *, full_page: bool = False) -> None:
        if not self.enabled:
            return
        path = self.root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        try:
            page.screenshot(path=str(path), full_page=full_page, timeout=8000)
        except Exception as exc:
            self.event("debug_screenshot_failed", path=relative, error=repr(exc),
                       page_url=self._page_url(page))

    def write_json(self, relative: str, payload) -> None:
        if not self.enabled:
            return
        path = self.root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        try:
            path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, default=str),
                            encoding="utf-8")
        except Exception as exc:
            self.event("debug_json_failed", path=relative, error=repr(exc))

    def write_text(self, relative: str, value: str) -> None:
        if not self.enabled:
            return
        path = self.root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        try:
            path.write_text(value, encoding="utf-8")
        except Exception as exc:
            self.event("debug_text_failed", path=relative, error=repr(exc))

    def finish_context(self, ctx) -> None:
        if not self.enabled:
            return
        try:
            self.event("debug_event_counts", counts=self._event_counts)
            ctx.tracing.stop(path=str(self.root / "trace.zip"))
            self.event("trace_stopped")
        except Exception as exc:
            self.event("trace_stop_failed", error=repr(exc))

    def close(self) -> None:
        if not self.enabled:
            return
        self.event("debug_finished")
        if self._stdout is not None:
            sys.stdout = self._stdout
        if self._stderr is not None:
            sys.stderr = self._stderr
        if self._events:
            self._events.close()
        if self._run_log:
            self._run_log.close()


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


# ── Data model ──────────────────────────────────────────────────────────────
@dataclass
class Ad:
    advertiser: str
    ad_type: str                      # link | video | in_facebook
    has_video: bool = False
    country: str | None = None
    displayed_domain: str = ""
    headline: str = ""
    ad_text: str = ""
    cta: str = ""
    cta_href: str = ""
    creative_img: str = ""
    video: str = ""
    screenshot: str = ""
    screenshot_ok: bool = True
    screenshot_issue: str = ""
    # filled by click-resolve (link ads only)
    landing_full: str | None = None
    landing_clean: str | None = None
    landing_screenshot: str | None = None
    landing_archive: str | None = None
    fb_ad_id: str | None = None
    feed_element_id: str | None = None
    facebook_page_url: str | None = None
    facebook_post_url: str | None = None
    utm: dict = field(default_factory=dict)
    # meta
    captured_at: str = field(default_factory=utc_now)

    def dedup_key(self) -> str:
        if self.fb_ad_id:
            return f"adid:{self.fb_ad_id}"
        parts = (
            self.advertiser,
            self.displayed_domain,
            self.headline,
            self.ad_text,
            self.cta,
            _creative_identity(self.creative_img),
        )
        return "creative:" + "\x1f".join(_norm_fingerprint_text(p) for p in parts)

    def coarse_key(self) -> str:
        """Textual identity used only to collapse media-loading states."""
        parts = (
            self.advertiser,
            self.displayed_domain,
            self.headline,
            self.ad_text,
            self.cta,
        )
        return "text:" + "\x1f".join(_norm_fingerprint_text(p) for p in parts)


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
    by_type: dict[str, int] = {}
    countries: dict[str, int] = {}
    domains: dict[str, int] = {}
    for ad in ads.values():
        by_type[ad.ad_type] = by_type.get(ad.ad_type, 0) + 1
        if ad.country:
            countries[ad.country] = countries.get(ad.country, 0) + 1
        domain = ad.landing_clean or ad.landing_full or ad.displayed_domain
        if domain:
            domains[domain] = domains.get(domain, 0) + 1
    resolved = [ad for ad in ads.values() if ad.landing_full or ad.landing_clean]
    screenshots = [ad for ad in ads.values() if ad.screenshot]
    return {
        "unique_ads": len(ads),
        "by_type": by_type,
        "countries": countries,
        "resolved_landings": len(resolved),
        "unique_landing_clean": len({
            ad.landing_clean or ad.landing_full for ad in resolved
            if ad.landing_clean or ad.landing_full
        }),
        "unique_fb_ad_ids": len({
            ad.fb_ad_id for ad in ads.values() if ad.fb_ad_id
        }),
        "unique_advertisers": len({
            ad.advertiser for ad in ads.values() if ad.advertiser
        }),
        "unique_domains": len(domains),
        "screenshot_attempted": len(screenshots),
        "screenshot_ok": sum(1 for ad in screenshots if ad.screenshot_ok is not False),
        "video_ads": sum(1 for ad in ads.values() if ad.has_video),
    }


def normalize_country(value: str | None) -> str | None:
    return _normalize_country(value)


# ── In-page detector (runs in the browser) ─────────────────────────────────
# Returns one record per glyph-detected ad story currently in the DOM. The
# detector starts from the sponsored glyph span and climbs to the smallest
# story-like container, then tags it with data-fbspy-id so Python can screenshot
# and click the exact same block.
DETECT_JS = r"""
() => {
  const GLYPHS = [0xF17E1, 0xF078B];
  const DOMAIN_RE = /^(https?:\/\/)?([a-z0-9-]+\.)+[a-z]{2,}(\/\S*)?$/i;
  const BAD = %BAD%;
  const PUA = c => (c>=0xE000&&c<=0xF8FF)||(c>=0xF0000);
  const strip = s => [...(s||"")]
    .filter(ch=>!PUA(ch.codePointAt(0)))
    .join("")
    .replace(/\u200e|\u200f|\u00a0/g, " ")
    .replace(/\s+/g, " ")
    .trim();
  const linesOf = el => (el && el.innerText || "")
    .split("\n").map(strip).filter(Boolean);
  const hasGlyphText = t => {
    for (const ch of (t||"")) if (GLYPHS.includes(ch.codePointAt(0))) return true;
    return false;
  };
  const isDomain = s => DOMAIN_RE.test((s||"").trim());
  const domainOf = s => {
    const m = (s||"").trim().match(DOMAIN_RE);
    if (!m) return "";
    return s.replace(/^https?:\/\//i,"").split("/")[0].toLowerCase();
  };
  const badDomain = dom => BAD.some(b => dom === b || dom.endsWith("." + b) || dom.includes(b));
  const hasLetters = s => /[\p{L}]/u.test(s||"");
  const wordCount = s => strip(s).split(/\s+/).filter(Boolean).length;
  const numericLike = s => /^[\d\s.,+]+([KkMmBb])?$/.test(strip(s).replace(/\s+/g, ""));
  const likelyCtaText = s => {
    const tx = strip(s);
    const words = wordCount(tx);
    return tx.length >= 2 && tx.length <= 42 && words >= 1 && words <= 5 &&
      hasLetters(tx) && !/\d/.test(tx) && !numericLike(tx) && !isDomain(tx) &&
      !/[a-z0-9-]+\.[a-z]{2,}/i.test(tx);
  };
  const engagementTop = root => {
    let top = Infinity;
    for (const el of root.querySelectorAll('a,[role="button"],[role="link"],[data-action-id]')) {
      const r = el.getBoundingClientRect();
      const tx = strip(el.innerText);
      if (r.width >= 40 && r.height >= 20 && numericLike(tx)) top = Math.min(top, r.top);
    }
    return top;
  };
  const bestButton = (root, maxTop = Infinity, minTop = -Infinity) => {
    let best = null;
    for (const el of root.querySelectorAll('a,[role="button"],[role="link"],[data-action-id]')) {
      const r = el.getBoundingClientRect();
      const tx = strip(el.innerText);
      if (r.top < minTop) continue;
      if (r.top >= maxTop) continue;
      if (r.width < 50 || r.height < 20 || r.height > 90 || !likelyCtaText(tx)) continue;
      const score = r.top * 10 + r.width;
      if (!best || score > best.score) best = {el, text:tx, score};
    }
    return best;
  };
  const videoPoster = video => {
    let root = video.parentElement;
    for (let depth = 0; root && depth < 4; root = root.parentElement, depth++) {
      const imgs = [...root.querySelectorAll('img[src][data-image-id]')];
      if (!imgs.length) continue;
      imgs.sort((a, b) =>
        (b.naturalWidth * b.naturalHeight) - (a.naturalWidth * a.naturalHeight));
      return imgs[0].src || "";
    }
    return "";
  };
  const biggestImgInfo = s => {
    let src = "", area = 0, bottom = -Infinity;
    for (const im of s.querySelectorAll('img[src]')) {
      if (!im.src || im.src.startsWith('data:')) continue;
      const r = im.getBoundingClientRect();
      const a = r.width * r.height;
      if (a > area) { area = a; src = im.src; bottom = r.bottom; }
    }
    for (const v of s.querySelectorAll('video')) {
      const r = v.getBoundingClientRect();
      const a = r.width * r.height;
      if (a > area) {
        area = a;
        bottom = r.bottom;
        // The visible video has a hidden poster sibling. Keep that stable URL
        // instead of retaining whichever small profile image was seen first.
        src = videoPoster(v);
      }
    }
    return {src, area, bottom};
  };
  const hasVideo = s => !!s.querySelector('video');
  const hasVideoCreative = s => {
    if (hasVideo(s)) return true;
    for (const el of s.querySelectorAll('button,[role="button"],[aria-label],video')) {
      const cls = (typeof el.className === "string" ? el.className : "").toLowerCase();
      const label = (el.getAttribute("aria-label") || "").toLowerCase();
      if (cls.includes("inline-video-icon") || label.includes("video")) return true;
    }
    return false;
  };
  const decodedAttributeValue = raw => (raw || "")
    .replace(/\\u0025/gi, "%")
    .replace(/\\u0026/gi, "&")
    .replace(/\\u003d/gi, "=")
    .replace(/\\u002f/gi, "/")
    .replace(/\\\//g, "/")
    .replace(/&amp;/gi, "&");
  const urlsFromAttribute = raw => {
    const value = decodedAttributeValue(raw);
    const urls = [];
    if (/^(?:https?:\/\/|\/l\.php\?)/i.test(value.trim())) {
      urls.push(value.trim());
    }
    for (const match of value.matchAll(/https?:\/\/[^"'\\\s<>]+/gi)) {
      urls.push(match[0]);
    }
    return [...new Set(urls)];
  };
  const outboundHrefInfo = (raw, displayedDomain, sourceScore) => {
    let parsed;
    try { parsed = new URL(raw, location.href); } catch (_) { return null; }
    if (!/^https?:$/.test(parsed.protocol)) return null;
    const host = parsed.hostname.toLowerCase().replace(/^www\./, "");
    const path = parsed.pathname.toLowerCase();
    let targetHost = host;
    const facebookHost = host === "facebook.com" || host.endsWith(".facebook.com");
    if (facebookHost) {
      if (!path.endsWith("/l.php")) return null;
      const target = parsed.searchParams.get("u");
      if (!target) return null;
      try {
        const targetUrl = new URL(target);
        targetHost = targetUrl.hostname.toLowerCase().replace(/^www\./, "");
      } catch (_) {
        return null;
      }
    }
    if (badDomain(targetHost)) return null;
    if (/\.(?:png|jpe?g|gif|webp|svg|mp4|m3u8)(?:$|\?)/i.test(parsed.href)) {
      return null;
    }
    const expected = (displayedDomain || "").replace(/^www\./, "");
    const domainMatch = expected && (
      targetHost === expected ||
      targetHost.endsWith("." + expected) ||
      expected.endsWith("." + targetHost)
    );
    return {
      href: parsed.href,
      score: sourceScore + (domainMatch ? 1000 : 0),
    };
  };
  const passiveHrefOf = (cardEl, buttonEl, story, displayedDomain) => {
    const candidates = [];
    const inspect = (node, baseScore) => {
      if (!node || !node.attributes) return;
      const explicitNames = new Set([
        "href", "data-lynx-uri", "data-href", "data-url",
        "data-destination-url", "data-endpoint",
      ]);
      for (const attr of node.attributes) {
        const name = (attr.name || "").toLowerCase();
        const explicit = explicitNames.has(name);
        if (!explicit && !/(?:url|uri|href|store|tracking)/.test(name)) continue;
        for (const rawUrl of urlsFromAttribute(attr.value || "")) {
          const info = outboundHrefInfo(
            rawUrl,
            displayedDomain,
            baseScore + (explicit ? 200 : 0),
          );
          if (info) candidates.push(info);
        }
      }
    };
    let node = buttonEl;
    for (let depth = 0; node && node !== story && depth < 7;
         node = node.parentElement, depth++) {
      inspect(node, 700 - depth * 20);
    }
    for (const child of cardEl.querySelectorAll(
      'a[href],[data-lynx-uri],[data-href],[data-url],[data-destination-url]'
    )) {
      inspect(child, 500);
    }
    node = cardEl;
    for (let depth = 0; node && node !== story && depth < 5;
         node = node.parentElement, depth++) {
      inspect(node, 400 - depth * 20);
    }
    candidates.sort((a, b) => b.score - a.score);
    return candidates.length ? candidates[0].href : "";
  };
  const linkCard = s => {
    let best = null;
    for (const d of s.querySelectorAll('div')) {
      const r = d.getBoundingClientRect();
      if (r.width < 240 || r.height < 30) continue;
      if (hasGlyphText(d.innerText || "")) continue;
      const dl = linesOf(d);
      if (dl.length < 2 || !isDomain(dl[0])) continue;
      const dom = domainOf(dl[0]);
      if (!dom || badDomain(dom)) continue;
      const btn = bestButton(d, engagementTop(s));
      const cta = btn ? btn.text : "";
      const candidate = {
        el: d,
        domain: dom,
        headline: dl[1] || "",
        cta,
        btn: btn ? btn.el : null,
        area: r.width * r.height,
      };
      if (!best || (candidate.btn && !best.btn) || candidate.area < best.area) best = candidate;
    }
    if (!best) return null;
    let target = best.btn;
    if (!target) {
      for (let el = best.el, depth = 0; el && el !== s && depth < 5;
           el = el.parentElement, depth++) {
        if (el.matches('a,[role="button"],[role="link"],[data-action-id]')) {
          target = el;
          break;
        }
      }
    }
    const br = best.btn ? best.btn.getBoundingClientRect() : null;
    const href = passiveHrefOf(best.el, target, s, best.domain);
    return {
      domain: best.domain,
      headline: best.headline,
      cta: best.cta,
      href,
      btn: br ? {x:Math.round(br.left+br.width/2), y:Math.round(br.top+br.height/2)} : null,
      target,
    };
  };
  const storyRootFor = sp => {
    for (let el = sp.parentElement, depth = 0; el && depth < 14; el = el.parentElement, depth++) {
      if (el.tagName !== "DIV") continue;
      const text = el.innerText || "";
      const r = el.getBoundingClientRect();
      if (r.width < 300 || r.height < 150 || r.height > 2600 ||
          text.length < 70 || text.length > 3500) continue;
      const img = biggestImgInfo(el);
      if (!linkCard(el) && !hasVideo(el) && img.area < 45000) continue;
      return el;
    }
    return null;
  };
  const advertiserOf = sp => {
    const sr = sp.getBoundingClientRect();
    const sponsored = new Set(linesOf(sp));
    const cands = [];
    for (let root = sp.parentElement, depth = 0; root && depth < 8; root = root.parentElement, depth++) {
      for (const el of root.querySelectorAll('a,[role="link"],span,div,h1,h2,h3,h4')) {
        if (el === sp || el.contains(sp) || sp.contains(el)) continue;
        const raw = el.innerText || "";
        if (hasGlyphText(raw)) continue;
        const r = el.getBoundingClientRect();
        if (r.bottom > sr.top + 6) continue;
        const tx = strip(raw);
        if (sponsored.has(tx)) continue;
        if (tx.length >= 2 && tx.length < 80 && hasLetters(tx))
          cands.push({line:tx, top:r.top, len:tx.length});
      }
      if (cands.length) break;
    }
    cands.sort((a,b)=>b.top-a.top || b.len-a.len);
    return cands.length ? cands[0].line : "";
  };
  const adTextOf = (root, sp, adv, card) => {
    const lines = linesOf(root);
    const sponsored = new Set(linesOf(sp));
    const skip = new Set([adv, card && card.domain, card && card.headline, card && card.cta]
      .filter(Boolean));
    for (const s of sponsored) skip.add(s);
    const domainIdx = card ? lines.findIndex(l => domainOf(l) === card.domain) : -1;
    const windowLines = domainIdx > 0 ? lines.slice(0, domainIdx) : lines;
    let best = "";
    for (const line of windowLines) {
      if (skip.has(line) || isDomain(line) || numericLike(line) || !hasLetters(line)) continue;
      if (likelyCtaText(line) && line.length <= 42) continue;
      if (line.length > best.length) best = line;
    }
    return best;
  };
  const facebookIdentityOf = root => {
    let adId = "", ownerId = "", postId = "";
    const values = [];
    for (const el of [root, ...root.querySelectorAll("*")]) {
      for (const attr of el.attributes || []) {
        const value = attr.value || "";
        if (!value.startsWith("{") ||
            !/(adid|top_level_post_id|story_fbid|content_owner_id_new)/.test(value)) continue;
        values.push(value);
      }
    }
    for (const value of values) {
      let payload;
      try { payload = JSON.parse(value); } catch (_) { continue; }
      const pending = [payload];
      let inspected = 0;
      while (pending.length && inspected++ < 150) {
        const item = pending.pop();
        if (!item || typeof item !== "object") continue;
        if (!adId && item.adid) adId = String(item.adid);
        if (!ownerId && item.content_owner_id_new) ownerId = String(item.content_owner_id_new);
        if (!ownerId && item.actor_id) ownerId = String(item.actor_id);
        if (!postId && item.top_level_post_id) postId = String(item.top_level_post_id);
        if (!postId && item.story_fbid) {
          postId = String(Array.isArray(item.story_fbid) ? item.story_fbid[0] : item.story_fbid);
        }
        if (!postId && item.post_id) postId = String(item.post_id);
        for (const child of Object.values(item)) {
          if (child && typeof child === "object") pending.push(child);
        }
      }
      if (adId && ownerId && postId) break;
    }
    return {
      fb_ad_id: adId,
      facebook_page_url: ownerId ? `https://m.facebook.com/${ownerId}` : "",
      facebook_post_url: ownerId && postId
        ? `https://m.facebook.com/${ownerId}/posts/${postId}`
        : "",
    };
  };

  const seenRoots = new Set();
  const out = [];
  const spans = [...document.querySelectorAll('span')]
    .filter(sp => (sp.getAttribute('style') || '').includes('#8a8d91') && hasGlyphText(sp.innerText));
  for (const sp of spans) {
    const el = storyRootFor(sp);
    if (!el || seenRoots.has(el)) continue;
    seenRoots.add(el);
    const card = linkCard(el);
    const adv = advertiserOf(sp);
    const adText = adTextOf(el, sp, adv, card);
    const img = biggestImgInfo(el);
    const facebook = facebookIdentityOf(el);
    const has_video = hasVideoCreative(el);
    let ad_type = card ? "link" : (has_video ? "video" : "in_facebook");
    const elementId = el.dataset.fbspyId ||
      ("fbspy_" + Date.now().toString(36) + "_" + out.length);
    el.dataset.fbspyId = elementId;
    if (card && card.target) card.target.dataset.fbspyClickTarget = elementId;
    out.push({
      advertiser: adv,
      ad_type,
      has_video,
      domain: card ? card.domain : "",
      headline: card ? card.headline : "",
      ad_text: adText.slice(0,300),
      cta: card ? (card.cta || "") : ((bestButton(el, engagementTop(el), img.bottom - 8) || {}).text || ""),
      cta_href: card ? (card.href || "") : "",
      creative_img: img.src,
      creative_area: Math.round(img.area || 0),
      btn: card ? card.btn : null,
      element_id: elementId,
      fb_ad_id: facebook.fb_ad_id,
      facebook_page_url: facebook.facebook_page_url,
      facebook_post_url: facebook.facebook_post_url,
    });
  }
  return out;
}
""".replace("%BAD%", json.dumps(list(BAD_DOMAINS)))


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


# Scroll a specific link ad's CTA to viewport center and return fresh coords.
SCROLL_CTA_JS = r"""
(payload) => {
  const GLYPHS=[0xF17E1,0xF078B];
  const DOMAIN_RE=/^(https?:\/\/)?([a-z0-9-]+\.)+[a-z]{2,}(\/\S*)?$/i;
  const PUA=c=>(c>=0xE000&&c<=0xF8FF)||(c>=0xF0000);
  const strip=s=>[...(s||'')].filter(ch=>!PUA(ch.codePointAt(0))).join('').replace(/\s+/g,' ').trim();
  const domain = typeof payload === 'string' ? payload : payload.domain;
  const elementId = typeof payload === 'string' ? '' : (payload.element_id || '');
  for (const old of document.querySelectorAll('[data-fbspy-cta]')) delete old.dataset.fbspyCta;
  const hasGlyph=s=>{for(const sp of s.querySelectorAll('span')){if(!(sp.getAttribute('style')||'').includes('#8a8d91'))continue;for(const ch of(sp.innerText||''))if(GLYPHS.includes(ch.codePointAt(0)))return true;}return false;};
  const words=s=>strip(s).split(/\s+/).filter(Boolean).length;
  const numericLike=s=>/^[\d\s.,+]+([KkMmBb])?$/.test(strip(s).replace(/\s+/g,''));
  const okText=s=>{const tx=strip(s);return tx.length>=2&&tx.length<=42&&words(tx)>=1&&words(tx)<=5&&/[\p{L}]/u.test(tx)&&!/\d/.test(tx)&&!numericLike(tx)&&!DOMAIN_RE.test(tx)&&!/[a-z0-9-]+\.[a-z]{2,}/i.test(tx);};
  const engagementTop=root=>{let top=Infinity;for(const el of root.querySelectorAll('a,[role="button"],[role="link"],[data-action-id]')){const r=el.getBoundingClientRect();const tx=strip(el.innerText);if(r.width>=40&&r.height>=20&&numericLike(tx))top=Math.min(top,r.top);}return top;};
  const bestButton=(root,maxTop=Infinity)=>{let best=null;for(const el of root.querySelectorAll('a,[role="button"],[role="link"],[data-action-id]')){const r=el.getBoundingClientRect();const tx=strip(el.innerText);if(r.top>=maxTop)continue;if(r.width<50||r.height<20||r.height>90||!okText(tx))continue;const score=r.top*10+r.width;if(!best||score>best.score)best={el,score};}return best&&best.el;};
  const markTarget=(target,kind)=>{if(!target)return null;target.scrollIntoView({block:'center'});target.dataset.fbspyCta='1';const r=target.getBoundingClientRect();return{x:Math.round(r.left+r.width/2),y:Math.round(r.top+r.height/2),kind};};
  if(elementId){
    const marked=document.querySelector(`[data-fbspy-click-target="${elementId}"]`);
    if(marked)return markTarget(marked,'detected_target');
  }
  const roots = [];
  if (elementId) {
    const exact = document.querySelector(`[data-fbspy-id="${elementId}"]`);
    if (exact) roots.push(exact);
  }
  if (!roots.length) roots.push(...document.querySelectorAll('div'));
  for(const el of roots){
    const t=el.innerText||'';if(t.length<80||t.length>3500)continue;if(!el.querySelector('img')&&!el.querySelector('video'))continue;
    if(el.getBoundingClientRect().width<300)continue;
    if(!hasGlyph(el))continue;
    for(const d of el.querySelectorAll('div')){
      if(hasGlyph(d))continue;
      const dl=(d.innerText||'').split("\n").map(x=>x.trim()).filter(Boolean);
      if(dl.length>=2&&DOMAIN_RE.test(dl[0])){
        const dom=dl[0].replace(/^https?:\/\//,'').split('/')[0].toLowerCase();
        if(dom!==domain)continue;
        let target=bestButton(d, engagementTop(el));
        if(!target){
          for(let node=d,depth=0;node&&node!==el&&depth<5;node=node.parentElement,depth++){
            if(node.matches('a,[role="button"],[role="link"],[data-action-id]')){target=node;break;}
          }
        }
        return markTarget(target,target===d?'link_card':'structural_target');
      }
    }
  }
  return null;
}
"""


OPEN_COMMENTS_FOR_PERMALINK_JS = r"""
({elementId}) => {
  const root = document.querySelector(`[data-fbspy-id="${elementId}"]`);
  if (!root) return {status: "root_not_found"};
  const norm = value => (value || "").toLocaleLowerCase().replace(/\s+/g, " ").trim();
  const positive = ["comment", "comentario", "comentar", "yorum"];
  const exclude = ["comments and reactions", "comentarios y reacciones"];
  for (const el of root.querySelectorAll('button,[role="button"]')) {
    const label = norm(`${el.getAttribute("aria-label") || ""} ${el.innerText || ""}`);
    if (!label || exclude.some(term => label.includes(norm(term)))) continue;
    if (!positive.some(term => label.includes(norm(term)))) continue;
    root.scrollIntoView({block: "center", inline: "nearest"});
    el.click();
    return {status: "clicked", label};
  }
  return {status: "control_not_found"};
}
"""


# ── URL helpers ─────────────────────────────────────────────────────────────
def parse_landing(url: str) -> tuple[str, dict, str | None]:
    """Return (clean_url, utm_dict, fb_ad_id)."""
    from urllib.parse import parse_qs, urlparse
    p = urlparse(url)
    clean = f"{p.scheme}://{p.netloc}{p.path}"
    qs = parse_qs(p.query)
    utm = {k: v[0] for k, v in qs.items() if k.startswith("utm_") or k in ("fbclid",)}

    def first_numeric(keys: tuple[str, ...]) -> str | None:
        for k in keys:
            for value in qs.get(k, []):
                m = re.search(r"\d{10,}", value)
                if m:
                    return m.group(0)
        return None

    # Prefer the real ad-level identifier. utm_id is commonly campaign-level,
    # so it is only a last-resort fallback.
    ad_id = first_numeric(("ad_id", "adid", "fb_ad_id", "utm_content"))
    if not ad_id:
        m = re.search(r"(?:[?&]|%26)(?:ad[_-]?id|adid|fb_ad_id|sub5)=(\d{10,})", url)
        if m:
            ad_id = m.group(1)
    if not ad_id:
        ad_id = first_numeric(("utm_term", "utm_id"))
    return clean, utm, ad_id


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


PASSIVE_MEDIA_GUARD_INSTALL_JS = r"""
() => {
  if (window.__fbSpyPassiveMediaGuard) {
    window.__fbSpyPassiveMediaGuard.pauseAll();
    return true;
  }
  const state = {
    blockedPlayCalls: 0,
    pauseEvents: 0,
    observedVideos: 0,
    pauseAll() {
      for (const video of document.querySelectorAll("video")) {
        state.observedVideos += 1;
        try {
          video.autoplay = false;
          video.muted = true;
          if (!video.paused) state.pauseEvents += 1;
          video.pause();
        } catch (_) {}
      }
    },
  };
  const nativePlay = HTMLMediaElement.prototype.play;
  HTMLMediaElement.prototype.play = function (...args) {
    state.blockedPlayCalls += 1;
    try {
      this.autoplay = false;
      this.muted = true;
      this.pause();
    } catch (_) {}
    return Promise.resolve();
  };
  state.nativePlay = nativePlay;
  const stopPlayback = event => {
    const video = event.target;
    if (!(video instanceof HTMLMediaElement)) return;
    try {
      video.autoplay = false;
      video.muted = true;
      if (!video.paused) state.pauseEvents += 1;
      video.pause();
    } catch (_) {}
  };
  document.addEventListener("play", stopPlayback, true);
  const startObserver = () => {
    if (!document.documentElement || state.observer) return;
    const observer = new MutationObserver(() => state.pauseAll());
    observer.observe(document.documentElement, {
      childList: true,
      subtree: true,
    });
    state.observer = observer;
    state.pauseAll();
  };
  window.__fbSpyPassiveMediaGuard = state;
  if (document.documentElement) startObserver();
  else document.addEventListener("DOMContentLoaded", startObserver, {once: true});
  return true;
}
"""


def install_passive_media_guard(page) -> bool:
    """Pause current and newly inserted videos for one passive feed document."""
    try:
        return bool(page.evaluate(PASSIVE_MEDIA_GUARD_INSTALL_JS))
    except Exception:
        return False


def prepare_passive_media_guard(page) -> dict[str, int | bool]:
    """Install play and media-request blockers before passive feed navigation."""
    stats: dict[str, int | bool] = {
        "init_script_installed": False,
        "media_route_installed": False,
        "blocked_media_requests": 0,
    }
    try:
        page.add_init_script(f"({PASSIVE_MEDIA_GUARD_INSTALL_JS})()")
        stats["init_script_installed"] = True
    except Exception:
        pass

    def block_media(route) -> None:
        try:
            if route.request.resource_type == "media":
                stats["blocked_media_requests"] += 1
                route.abort()
                return
            route.continue_()
        except Exception:
            try:
                route.abort()
            except Exception:
                pass

    try:
        page.route("**/*", block_media)
        stats["media_route_installed"] = True
    except Exception:
        pass
    return stats


def _pause_all_videos(page) -> None:
    try:
        page.evaluate(
            """
            () => {
              const guard = window.__fbSpyPassiveMediaGuard;
              if (guard && typeof guard.pauseAll === "function") {
                guard.pauseAll();
                return;
              }
              for (const video of document.querySelectorAll("video")) {
                try {
                  video.autoplay = false;
                  video.muted = true;
                  video.pause();
                } catch (_) {}
              }
            }
            """
        )
    except Exception:
        pass


def _passive_media_guard_stats(page) -> dict[str, int | bool]:
    try:
        payload = page.evaluate(
            """
            () => {
              const guard = window.__fbSpyPassiveMediaGuard;
              return guard ? {
                installed: true,
                blocked_play_calls: Number(guard.blockedPlayCalls || 0),
                pause_events: Number(guard.pauseEvents || 0),
                observed_videos: Number(guard.observedVideos || 0),
              } : {
                installed: false,
                blocked_play_calls: 0,
                pause_events: 0,
                observed_videos: 0,
              };
            }
            """
        )
        if isinstance(payload, dict):
            return {
                "installed": bool(payload.get("installed")),
                "blocked_play_calls": int(payload.get("blocked_play_calls") or 0),
                "pause_events": int(payload.get("pause_events") or 0),
                "observed_videos": int(payload.get("observed_videos") or 0),
            }
    except Exception:
        pass
    return {
        "installed": False,
        "blocked_play_calls": 0,
        "pause_events": 0,
        "observed_videos": 0,
    }


def neutralize_profile_pages(page, ctx) -> None:
    """Leave the persistent profile without a visible ad or playing media."""
    try:
        page.evaluate(
            """
            () => {
              for (const video of document.querySelectorAll("video")) {
                try { video.pause(); video.muted = true; } catch (_) {}
              }
            }
            """
        )
    except Exception:
        pass
    _close_landing_tabs(ctx, keep=page)
    try:
        page.goto("about:blank", wait_until="commit", timeout=5000)
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


def _is_fb_feed_url(url: str) -> bool:
    from urllib.parse import urlparse
    try:
        p = urlparse(url)
    except Exception:
        return False
    host = p.netloc.lower()
    return host.endswith("facebook.com") and p.path in ("", "/", "/home.php")


def _facebook_login_required(page) -> bool:
    """Distinguish a logged-out Facebook page from an empty authenticated feed."""
    try:
        return bool(page.evaluate(
            """
            () => {
              const path = window.location.pathname.toLowerCase();
              const authPath = (
                path.startsWith("/login")
                || path.startsWith("/checkpoint")
                || path.startsWith("/recover")
                || path.startsWith("/unified/login")
              );
              const password = document.querySelector('input[type="password"]');
              const identity = document.querySelector(
                'input[name="email"], input[type="email"], input[name="phone"]'
              );
              return authPath || Boolean(password && identity);
            }
            """
        ))
    except Exception:
        return False


def _goto_with_retry(
    page,
    url: str,
    *,
    timeout: int,
    attempts: int = 5,
    base_delay_seconds: float = 1.5,
):
    """Retry navigation while an Octo profile's proxy is still coming up."""
    total_attempts = max(1, attempts)
    ignored_proxy_certificate_error = False
    for attempt in range(1, total_attempts + 1):
        try:
            return page.goto(
                url,
                wait_until="domcontentloaded",
                timeout=timeout,
            )
        except Exception as exc:
            if (
                not ignored_proxy_certificate_error
                and PROXY_CERTIFICATE_AUTHORITY_ERROR in str(exc)
                and _ignore_proxy_certificate_errors(page)
            ):
                ignored_proxy_certificate_error = True
                print(
                    "[navigation retry] accepted proxy certificate authority "
                    f"for this browser session; attempt={attempt}/{total_attempts}",
                    flush=True,
                )
                continue
            transient = isinstance(exc, PlaywrightTimeoutError) or any(
                code in str(exc) for code in TRANSIENT_NAVIGATION_ERRORS
            )
            if not transient or attempt >= total_attempts:
                raise
            delay = base_delay_seconds * attempt
            print(
                f"[navigation retry] attempt={attempt}/{total_attempts} "
                f"delay={delay:.1f}s error={exc}",
                flush=True,
            )
            time.sleep(delay)
    raise RuntimeError("navigation retries exhausted")


def _ignore_proxy_certificate_errors(page) -> bool:
    """Allow an Octo proxy's untrusted CA only in the current CDP session."""
    try:
        session = page.context.new_cdp_session(page)
        session.send("Security.setIgnoreCertificateErrors", {"ignore": True})
    except Exception as exc:
        print(
            f"[navigation] could not accept proxy certificate authority: {exc}",
            flush=True,
        )
        return False
    return True


def _recover_feed(page, feed_url: str = "https://m.facebook.com/") -> None:
    try:
        if not _is_fb_feed_url(page.url):
            _goto_with_retry(page, feed_url, timeout=12000, attempts=3)
            time.sleep(3)
    except Exception:
        pass


def resolve_facebook_post_url(
    page,
    ad: Ad,
    element_id: str | None,
    *,
    feed_url: str = "https://m.facebook.com/",
    debug: DebugRecorder | None = None,
    debug_id: int = 0,
) -> bool:
    """Open a post's comments read-only to recover IDs absent from static ads."""
    if ad.facebook_post_url:
        return True
    if not element_id:
        return False
    try:
        opened = page.evaluate(
            OPEN_COMMENTS_FOR_PERMALINK_JS,
            {"elementId": element_id},
        )
        if opened.get("status") != "clicked":
            return False
        deadline = time.monotonic() + 5.0
        identity = None
        while time.monotonic() < deadline:
            identity = _facebook_post_identity_from_url(page.url)
            if identity:
                break
            page.wait_for_timeout(250)
        if not identity:
            page.keyboard.press("Escape")
            return False
        owner_id, _post_id = identity
        observed_post_url = _normalized_facebook_post_url(page.url)
        if not observed_post_url:
            return False
        ad.facebook_page_url = f"https://m.facebook.com/{owner_id}"
        ad.facebook_post_url = observed_post_url
        if debug:
            debug.event(
                "facebook_post_url_resolved",
                debug_id=debug_id,
                fb_ad_id=ad.fb_ad_id,
                facebook_post_url=ad.facebook_post_url,
                observed_url=page.url,
            )
        return True
    except Exception as exc:
        if debug:
            debug.event(
                "facebook_post_url_failed",
                debug_id=debug_id,
                error=repr(exc),
            )
        return False
    finally:
        try:
            if not _is_fb_feed_url(page.url):
                page.go_back(wait_until="domcontentloaded", timeout=12000)
                page.wait_for_timeout(750)
        except Exception:
            pass
        _recover_feed(page, feed_url=feed_url)


def _facebook_post_identity_from_url(url: str) -> tuple[str, str] | None:
    from urllib.parse import parse_qs, urlparse

    try:
        parsed = urlparse(url)
    except ValueError:
        return None
    host = (parsed.hostname or "").casefold()
    if host != "facebook.com" and not host.endswith(".facebook.com"):
        return None
    query = parse_qs(parsed.query)
    owner_id = (query.get("id") or [""])[0]
    post_id = (query.get("story_fbid") or [""])[0]
    if owner_id and post_id:
        return owner_id, post_id
    parts = [part for part in parsed.path.split("/") if part]
    if "posts" in parts:
        index = parts.index("posts")
        if index > 0 and index + 1 < len(parts):
            return parts[index - 1], parts[index + 1]
    return None


def _normalized_facebook_post_url(url: str) -> str | None:
    """Return a stable direct URL while discarding Facebook tracking state."""
    from urllib.parse import parse_qs, urlencode, urlparse

    identity = _facebook_post_identity_from_url(url)
    if not identity:
        return None
    owner_id, post_id = identity
    parsed = urlparse(url)
    query = parse_qs(parsed.query)
    if query.get("story_fbid") and query.get("id"):
        return "https://m.facebook.com/story.php?" + urlencode({
            "story_fbid": post_id,
            "id": owner_id,
        })
    return f"https://m.facebook.com/{owner_id}/posts/{post_id}"


def _external_landing_url(url: str | None) -> str | None:
    """Return an external landing URL, including FB outbound l.php redirects."""
    if not url or not url.startswith(("http://", "https://")):
        return None
    try:
        from urllib.parse import parse_qs, urlparse
        p = urlparse(url)
        host = (p.hostname or "").lower()
        if not host.endswith("facebook.com"):
            return url
        if p.path.endswith("/l.php"):
            target = parse_qs(p.query).get("u", [None])[0]
            if target and target.startswith(("http://", "https://")):
                target_host = (urlparse(target).hostname or "").lower()
                if not target_host.endswith("facebook.com"):
                    return target
    except Exception:
        pass
    return None


# ── Click-resolve a link ad that is CURRENTLY in view ───────────────────────
def resolve_in_view(page, ctx, ad: Ad, btn: dict | None, element_id: str | None,
                    run_dir: Path,
                    debug: DebugRecorder | None = None, debug_id: int = 0,
                    feed_url: str = "https://m.facebook.com/",
                    archive_landing: bool = True,
                    landing_archive_timeout: float = 20.0,
                    landing_archive_max_resources: int = 120) -> None:
    """Scroll the ad's CTA into view, click it, capture the full landing URL.
    Saves the landing tab url after it settles, then closes that tab and
    recovers. ad data is already stored, so failure here loses nothing."""
    prefix = f"resolve/{debug_id:04d}"
    if debug:
        debug.event("resolve_start", debug_id=debug_id, advertiser=ad.advertiser,
                    domain=ad.displayed_domain, element_id=element_id,
                    feed_url=DebugRecorder._page_url(page),
                    pages=[DebugRecorder._page_url(p) for p in ctx.pages])
        debug.screenshot(page, f"{prefix}_before.png")
    # Clean slate: close every extra tab so the landing opened by THIS click is
    # unambiguous. Keep only the FB feed page we are driving.
    _close_landing_tabs(ctx, keep=page)
    # The CTA coords from detection may be off-screen (below viewport). Scroll
    # the ad's domain card to center, then re-read fresh button coords.
    payload = {"domain": ad.displayed_domain, "element_id": element_id or ""}
    fresh = page.evaluate(SCROLL_CTA_JS, payload)
    if not fresh:
        if debug:
            debug.event("resolve_no_cta", debug_id=debug_id, payload=payload)
            debug.screenshot(page, f"{prefix}_no_cta.png")
        return
    time.sleep(0.8)
    fresh = page.evaluate(SCROLL_CTA_JS, payload) or fresh
    # The landing opens in a NEW tab. ctx.expect_page() is the reliable way to
    # capture it (a manual ctx.pages poll races the async tab registration).
    full = None
    new_page = None
    try:
        with ctx.expect_page(timeout=8000) as new_info:
            page.locator('[data-fbspy-cta="1"]').first.click(
                timeout=1500, no_wait_after=True,
            )
        new_page = new_info.value
        try:
            new_page.wait_for_load_state("domcontentloaded", timeout=12000)
        except Exception:
            pass
        time.sleep(1.0)               # let the redirect chain settle
        u = new_page.url
        full = _external_landing_url(u)
        if debug:
            debug.event("resolve_new_page", debug_id=debug_id, url=u,
                        external=full, pages=[DebugRecorder._page_url(p) for p in ctx.pages])
            debug.screenshot(new_page, f"{prefix}_landing.png")
    except Exception as exc:
        # Some mobile ad clicks navigate the current tab instead of opening a
        # new page. Capture that URL too, then _recover_feed() will bring us
        # back to the feed. If it stayed on Facebook, this was just an in-FB
        # overlay/form and there is no external landing to record.
        try:
            time.sleep(1.0)
            u = page.url
            full = _external_landing_url(u)
        except Exception:
            pass
        if not full:
            for candidate in reversed(list(ctx.pages)):
                if candidate == page or DebugRecorder._page_url(candidate).startswith("devtools"):
                    continue
                candidate_url = DebugRecorder._page_url(candidate)
                recovered = _external_landing_url(candidate_url)
                if recovered:
                    new_page, full = candidate, recovered
                    if debug:
                        debug.event("resolve_recovered_page", debug_id=debug_id,
                                    url=candidate_url, external=full)
                        debug.screenshot(candidate, f"{prefix}_recovered_landing.png")
                    break
        if debug:
            if full:
                debug.event("resolve_click_timeout_recovered", debug_id=debug_id,
                            timeout=repr(exc), external=full,
                            feed_url=DebugRecorder._page_url(page),
                            pages=[DebugRecorder._page_url(p) for p in ctx.pages])
            else:
                debug.event("resolve_click_error", debug_id=debug_id, error=repr(exc),
                            traceback=traceback.format_exc(),
                            feed_url=DebugRecorder._page_url(page),
                            pages=[DebugRecorder._page_url(p) for p in ctx.pages])
                debug.screenshot(page, f"{prefix}_click_error.png")
    if full:
        clean, utm, ad_id = parse_landing(full)
        ad.landing_full, ad.landing_clean, ad.utm = full, clean, utm
        ad.fb_ad_id = ad_id or ad.fb_ad_id
        archive_page = new_page
        if archive_page is None and not _is_fb_feed_url(DebugRecorder._page_url(page)):
            archive_page = page
        screenshot_path = None
        if archive_page is not None:
            try:
                wait_for_landing_page_ready(
                    archive_page,
                    timeout_seconds=landing_archive_timeout,
                )
                screenshot_path = save_landing_screenshot_from_browser(
                    archive_page,
                    run_dir,
                    source_index=debug_id,
                    domain=ad.displayed_domain,
                    url=full,
                    timeout_seconds=landing_archive_timeout,
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
                    timeout_seconds=landing_archive_timeout,
                    max_resources=landing_archive_max_resources,
                    wait_until_ready=False,
                    fallback_screenshot_path=(
                        run_dir / screenshot_path if screenshot_path else None
                    ),
                )
                if archive_path:
                    ad.landing_archive = archive_path
                    print(
                        f"  archived {ad.displayed_domain} -> {archive_path}",
                        flush=True,
                    )
                    if debug:
                        debug.event(
                            "landing_archived",
                            debug_id=debug_id,
                            archive=archive_path,
                        )
            except Exception as exc:
                print(
                    f"  archive failed {ad.displayed_domain}: {exc!r}",
                    flush=True,
                )
                if debug:
                    debug.event(
                        "landing_archive_failed",
                        debug_id=debug_id,
                        error=repr(exc),
                    )
    try:
        if new_page and not new_page.is_closed():
            new_page.close(run_before_unload=False)
    except Exception:
        pass
    _close_landing_tabs(ctx, keep=page)
    try:
        page.keyboard.press("Escape")
    except Exception:
        pass
    _recover_feed(page, feed_url=feed_url)
    if debug:
        debug.event("resolve_finish", debug_id=debug_id, full=ad.landing_full,
                    clean=ad.landing_clean, fb_ad_id=ad.fb_ad_id,
                    feed_url=DebugRecorder._page_url(page),
                    pages=[DebugRecorder._page_url(p) for p in ctx.pages])
        debug.screenshot(page, f"{prefix}_after.png")


def _close_landing_tabs(ctx, keep=None) -> None:
    """Close every tab except the driven feed page and devtools."""
    for p in list(ctx.pages):
        try:
            if keep is not None and p == keep:
                continue
            u = p.url
            if u.startswith("devtools"):
                continue
            p.close()
        except Exception:
            pass


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
    interest_safe_overrides: list[str] = []
    if interest_safe_mode:
        if do_resolve:
            interest_safe_overrides.append("landing_resolution")
        if record_videos:
            interest_safe_overrides.append("video_recording")
        if resolve_post_urls:
            interest_safe_overrides.append("permalink_resolution")
        do_resolve = False
        record_videos = False
        resolve_post_urls = False
    shots_dir = run_dir / "screens"
    if shots:
        shots_dir.mkdir(parents=True, exist_ok=True)
    videos_dir = run_dir / "videos"
    if record_videos:
        videos_dir.mkdir(parents=True, exist_ok=True)
    ads: dict[str, Ad] = {}
    coarse_keys: dict[str, set[str]] = {}
    lazy_media_keys: set[str] = set()
    seen_fb_ad_ids: set[str] = set()
    duplicate_coarse_keys: set[str] = set()
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
            if interest_safe_mode:
                _pause_all_videos(page)
            try:
                rows = page.evaluate(DETECT_JS)
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
                ad = Ad(
                    advertiser=r["advertiser"], ad_type=r["ad_type"],
                    has_video=bool(r.get("has_video")),
                    country=country,
                    displayed_domain=r["domain"], headline=r["headline"],
                    ad_text=r["ad_text"], cta=r["cta"],
                    cta_href=r.get("cta_href") or "",
                    creative_img=r["creative_img"],
                    feed_element_id=r.get("element_id"),
                    fb_ad_id=r.get("fb_ad_id") or None,
                    facebook_page_url=r.get("facebook_page_url") or None,
                    facebook_post_url=r.get("facebook_post_url") or None,
                )
                key = ad.dedup_key()
                coarse_key = ad.coarse_key()
                if coarse_key in duplicate_coarse_keys:
                    if debug:
                        debug.event(
                            "confirmed_duplicate_skip",
                            scroll=scrolls,
                            coarse_key=coarse_key,
                            advertiser=ad.advertiser,
                            domain=ad.displayed_domain,
                        )
                    continue
                creative_area = int(r.get("creative_area") or 0)
                lazy_media = _is_lazy_video_image(
                    ad.creative_img, has_video=ad.has_video, creative_area=creative_area)
                if key in ads:
                    if r.get("element_id"):
                        ads[key].feed_element_id = r["element_id"]
                    if debug:
                        debug.event("dedup_skip", scroll=scrolls, dedup_key=key,
                                    advertiser=ad.advertiser, domain=ad.displayed_domain,
                                    headline=ad.headline, creative_img=ad.creative_img)
                    continue
                siblings = coarse_keys.get(coarse_key, set())
                if lazy_media and siblings:
                    if debug:
                        debug.event("lazy_media_duplicate_skip", scroll=scrolls,
                                    coarse_key=coarse_key, existing_keys=sorted(siblings),
                                    advertiser=ad.advertiser, domain=ad.displayed_domain,
                                    headline=ad.headline, creative_img=ad.creative_img,
                                    creative_area=creative_area)
                    continue
                inherited = None
                if not lazy_media:
                    for old_key in list(siblings & lazy_media_keys):
                        old = ads.pop(old_key, None)
                        coarse_keys[coarse_key].discard(old_key)
                        lazy_media_keys.discard(old_key)
                        if old and inherited is None:
                            inherited = old
                        if debug:
                            debug.event("lazy_media_replaced", old_key=old_key,
                                        new_key=key, coarse_key=coarse_key)
                if inherited:
                    for attr in (
                        "landing_full",
                        "landing_clean",
                        "landing_screenshot",
                        "landing_archive",
                        "fb_ad_id",
                        "facebook_page_url",
                        "facebook_post_url",
                        "utm",
                        "video",
                    ):
                        value = getattr(inherited, attr)
                        if value:
                            setattr(ad, attr, value)
                captured += 1
                debug_id = captured
                if debug and r.get("element_id"):
                    try:
                        html = page.locator(
                            f'[data-fbspy-id="{r["element_id"]}"]').first.evaluate(
                                "el => el.outerHTML", timeout=5000)
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
                ads[key] = ad
                coarse_keys.setdefault(coarse_key, set()).add(key)
                if lazy_media:
                    lazy_media_keys.add(key)
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
                        if ad.fb_ad_id and ad.fb_ad_id in seen_fb_ad_ids:
                            duplicate_fb_ad_ids += 1
                            duplicate_coarse_keys.add(coarse_key)
                            ads.pop(key, None)
                            coarse_keys.get(coarse_key, set()).discard(key)
                            lazy_media_keys.discard(key)
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
                        if ad.fb_ad_id:
                            seen_fb_ad_ids.add(ad.fb_ad_id)
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
                page.evaluate(
                    """dy => window.scrollBy({top: dy, left: 0, behavior: "smooth"})""",
                    actual_scroll_px,
                )
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
def main() -> int:
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
    args = ap.parse_args()

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
    debug = DebugRecorder(run_dir, args.debug)
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

"""Resolve uncertain ad landings without using the authenticated FB context."""

from __future__ import annotations

import argparse
import ipaddress
import json
import re
import socket
import sys
import time
import traceback
from pathlib import Path
from typing import Any
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from playwright.sync_api import Error as PlaywrightError
from playwright.sync_api import sync_playwright

from app.services import facebook_runner
from app.services.facebook.calibration import CalibrationTarget
from app.services.facebook.landing_archive import (
    archive_landing_page_from_browser,
    save_landing_screenshot_from_browser,
    wait_for_landing_page_ready,
)
from app.settings import get_config

_META_HOST_SUFFIXES = (
    "facebook.com",
    "facebook.net",
    "fbcdn.net",
    "instagram.com",
)
_LOCAL_HOST_SUFFIXES = (
    ".internal",
    ".local",
    ".localhost",
    ".home",
    ".lan",
)
_PROFILE_TRACKING_PARAMS = {
    "fbclid",
    "fb_action_ids",
    "fb_action_types",
    "fb_source",
    "mibextid",
    "__tn__",
    "__cft__",
}

_LOCATE_ANONYMOUS_POST_JS = r"""
({advertiser, displayedDomain, headline, cta, elementId}) => {
  const norm = value => (value || "")
    .toLocaleLowerCase()
    .replace(/\s+/g, " ")
    .trim();
  const expectedAdvertiser = norm(advertiser);
  const expectedDomain = norm(displayedDomain).replace(/^www\./, "");
  const expectedHeadline = norm(headline);
  const expectedCta = norm(cta);
  if (!expectedAdvertiser) return {status: "missing_advertiser"};

  const controls = [...document.querySelectorAll(
    'a,button,[role="button"],[role="link"],[data-action-id],[tabindex="0"]'
  )];
  const controlLabel = el => norm(
    `${el.getAttribute("aria-label") || ""} ${el.innerText || ""}`
  );
  const controlCandidates = controls.map(el => {
    const label = controlLabel(el);
    let score = 0;
    if (expectedCta && label === expectedCta) score += 300;
    else if (expectedCta && label.includes(expectedCta)) score += 180;
    const href = el.href || el.getAttribute("href") || "";
    if (href && expectedDomain) {
      try {
        const host = new URL(href, location.href)
          .hostname.toLocaleLowerCase().replace(/^www\./, "");
        if (host === expectedDomain || host.endsWith(`.${expectedDomain}`)) {
          score += 240;
        }
      } catch (_) {}
    }
    return {el, label, score};
  }).filter(item => item.score > 0);
  if (expectedCta) {
    const textSeeds = [...document.querySelectorAll("span,div")]
      .filter(el => {
        if (norm(el.innerText) !== expectedCta) return false;
        return ![...el.children].some(
          child => norm(child.innerText) === expectedCta
        );
      });
    for (const seed of textSeeds) {
      let control = null;
      for (let node = seed, depth = 0;
           node && node !== document.body && depth < 7;
           node = node.parentElement, depth++) {
        if (node.matches(
          'a,button,[role="button"],[role="link"],[data-action-id],[tabindex="0"]'
        )) {
          control = node;
          break;
        }
      }
      controlCandidates.push({
        el: control || seed,
        label: controlLabel(control || seed),
        score: control ? 360 : 320,
      });
    }
  }

  let best = null;
  for (const item of controlCandidates) {
    for (let root = item.el; root && root !== document.body;
         root = root.parentElement) {
      if (root.tagName !== "DIV") continue;
      const text = norm(root.innerText);
      if (!text.includes(expectedAdvertiser)) continue;
      const hasDomain = expectedDomain && text.includes(expectedDomain);
      const hasHeadline = expectedHeadline && text.includes(expectedHeadline);
      const hasCta = expectedCta && text.includes(expectedCta);
      if (!hasDomain && !hasHeadline && !hasCta) continue;
      const rect = root.getBoundingClientRect();
      if (rect.width < 280 || rect.height < 120 || rect.height > 2600) continue;
      const area = rect.width * rect.height;
      const score = item.score + (hasDomain ? 160 : 0)
        + (hasHeadline ? 100 : 0) - Math.round(area / 10000);
      if (!best || score > best.score) {
        best = {root, control:item.el, label:item.label, score};
      }
      break;
    }
  }
  if (!best) return {
    status: "post_not_found",
    advertiser_in_page: norm(document.body.innerText)
      .includes(expectedAdvertiser),
    domain_in_page: expectedDomain
      ? norm(document.body.innerText).includes(expectedDomain)
      : false,
    cta_in_page: expectedCta
      ? norm(document.body.innerText).includes(expectedCta)
      : false,
  };
  best.root.dataset.fbspyId = elementId;
  best.control.dataset.fbspyClickTarget = elementId;
  best.root.scrollIntoView({block: "center", inline: "nearest"});
  return {
    status: "located",
    element_id: elementId,
    advertiser,
    strategy: "anonymous_metadata_cta",
    cta_label: best.label,
  };
}
"""


def main() -> int:
    args = _build_parser().parse_args()
    run_dir = args.run_dir.expanduser().resolve()
    source_path = (
        args.source.expanduser().resolve()
        if args.source
        else run_dir / "ads.prefilter.json"
    )
    output_path = (
        args.output.expanduser().resolve()
        if args.output
        else run_dir / "ads.isolated.json"
    )
    summary_path = run_dir / "isolated_resolution_summary.json"
    events_path = run_dir / "isolated_resolution_events.jsonl"

    if not source_path.exists():
        _write_json(summary_path, {
            "status": "no_prefilter_file",
            "source": str(source_path),
        })
        return 2

    rows = _load_ads(source_path)
    candidates: list[tuple[int, str, str]] = []
    for index, row in enumerate(rows):
        if row.get("relevance_gate") != "hold":
            continue
        source, target, issue = _resolution_candidate(row)
        if target:
            candidates.append((index, source, target))
            continue
        row["isolated_resolution"] = {
            "status": issue,
            "cookie_isolated": True,
            "separate_browser_context": True,
            "facebook_cookie_count_before": 0,
            "authenticated_profile_context": False,
            "active_profile_actions_started": False,
            "isolated_navigation_started": False,
            "external_navigation_started": False,
        }

    if not candidates:
        _write_json(output_path, rows)
        summary = _summary(rows, status="completed")
        _write_json(summary_path, summary)
        print("[isolated resolver] no resolvable held cards", flush=True)
        return 0

    config = get_config()
    profile_uuid = args.octo_profile_uuid or config.facebook.octo_profile_uuid
    facebook_runner.OCTO_API = f"http://{args.octo_host}:{args.octo_port}"
    facebook_runner.OCTO_PROFILE_UUID = profile_uuid
    facebook_runner.OCTO_HEADLESS = args.octo_headless

    try:
        ws_endpoint, connection_data = facebook_runner.get_cdp_endpoint()
        ws_endpoint = facebook_runner.rewrite_cdp_endpoint_host(
            ws_endpoint,
            args.octo_host,
        )
        _append_event(events_path, {
            "at": facebook_runner.utc_now(),
            "kind": "started",
            "profile_uuid": profile_uuid,
            "profile_country": facebook_runner.normalize_country(
                connection_data.get("country")
            ),
            "candidates": len(candidates),
        })
        with sync_playwright() as playwright:
            browser = playwright.chromium.connect_over_cdp(ws_endpoint)
            profile_context = browser.contexts[0] if browser.contexts else None
            resolved_cache: dict[str, dict[str, Any]] = {}
            for sequence, (row_index, source, target) in enumerate(
                candidates,
                start=1,
            ):
                cache_key = f"{source}:{target}"
                if cache_key in resolved_cache:
                    _reuse_resolution(
                        rows[row_index],
                        resolved_cache[cache_key],
                        source_row_index=resolved_cache[cache_key]["row_index"],
                    )
                    continue
                context = _new_isolated_context(browser)
                try:
                    if context == profile_context:
                        raise RuntimeError(
                            "isolated resolver received the persistent profile context"
                        )
                    facebook_cookies = context.cookies(
                        ["https://www.facebook.com", "https://m.facebook.com"]
                    )
                    if facebook_cookies:
                        raise RuntimeError(
                            "isolated context unexpectedly contains Facebook cookies"
                        )
                    _append_event(events_path, {
                        "at": facebook_runner.utc_now(),
                        "kind": "isolation_verified",
                        "row_index": row_index,
                        "source": source,
                        "separate_browser_context": True,
                        "facebook_cookie_count_before": len(facebook_cookies),
                    })
                    network_guard = _NetworkGuard(
                        allow_anonymous_facebook=(
                            source == "anonymous_facebook_post"
                        )
                    )
                    _configure_isolated_context(context, network_guard)
                    resolved, result = _resolve_one(
                        context,
                        rows[row_index],
                        target,
                        source=source,
                        sequence=sequence,
                        run_dir=run_dir,
                        args=args,
                        network_guard=network_guard,
                        facebook_cookie_count_before=len(facebook_cookies),
                    )
                    rows[row_index] = resolved
                    resolved_cache[cache_key] = {
                        "row_index": row_index,
                        "row": resolved,
                    }
                    _append_event(events_path, {
                        "at": facebook_runner.utc_now(),
                        "kind": "candidate_finished",
                        "row_index": row_index,
                        **result,
                    })
                    _write_json(output_path, rows)
                finally:
                    context.close()

        _write_json(output_path, rows)
        summary = _summary(rows, status="completed")
        _write_json(summary_path, summary)
        _append_event(
            events_path,
            {"at": facebook_runner.utc_now(), "kind": "finished", **summary},
        )
        if (
            summary["authenticated_profile_actions_started"]
            or summary["isolation_violations"]
        ):
            print(
                "[isolated resolver invariant] authenticated profile action detected",
                file=sys.stderr,
                flush=True,
            )
            return 4
        print(
            f"[isolated resolver] held={summary['held']} "
            f"resolved={summary['resolved']} "
            f"unresolved={summary['unresolved']} "
            f"meta_blocked={summary['meta_requests_blocked']}",
            flush=True,
        )
        return 0
    except Exception as exc:
        _write_json(output_path, rows)
        summary = _summary(rows, status="infrastructure_error")
        summary["error"] = repr(exc)
        summary["traceback"] = traceback.format_exc()
        _write_json(summary_path, summary)
        print(f"[isolated resolver error] {exc!r}", file=sys.stderr, flush=True)
        return 2


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-dir", type=Path, required=True)
    parser.add_argument("--source", type=Path, default=None)
    parser.add_argument("--output", type=Path, default=None)
    parser.add_argument("--octo-host", default="127.0.0.1")
    parser.add_argument("--octo-port", type=int, default=58888)
    parser.add_argument("--octo-profile-uuid", default="")
    parser.add_argument("--octo-headless", action="store_true")
    parser.add_argument("--timeout-ms", type=int, default=30_000)
    parser.add_argument("--landing-ready-seconds", type=float, default=12.0)
    parser.add_argument("--landing-archive-max-resources", type=int, default=80)
    parser.add_argument(
        "--archive-landings",
        action=argparse.BooleanOptionalAction,
        default=False,
    )
    return parser


def isolated_external_url(value: Any) -> tuple[str, str]:
    """Extract a direct public landing URL without following Facebook l.php."""
    candidate = facebook_runner._external_landing_url(str(value or "").strip())
    if not candidate:
        return "", "missing_or_internal_passive_cta"
    try:
        parsed = urlsplit(candidate)
    except ValueError:
        return "", "invalid_passive_cta"
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        return "", "invalid_passive_cta"
    if parsed.username or parsed.password:
        return "", "credentialed_passive_cta_rejected"
    host = parsed.hostname.casefold().rstrip(".")
    if _is_meta_host(host) or not _host_is_public(host):
        return "", "unsafe_passive_cta_rejected"
    clean_query = urlencode(
        [
            (key, value)
            for key, value in parse_qsl(parsed.query, keep_blank_values=True)
            if key.casefold() not in _PROFILE_TRACKING_PARAMS
        ],
        doseq=True,
    )
    return (
        urlunsplit((
            parsed.scheme,
            parsed.netloc,
            parsed.path or "/",
            clean_query,
            "",
        )),
        "",
    )


def _resolution_candidate(raw: dict[str, Any]) -> tuple[str, str, str]:
    target, issue = isolated_external_url(raw.get("cta_href"))
    if target:
        return "passive_cta_href", target, ""
    post_url = _valid_facebook_post_url(raw.get("facebook_post_url"))
    if post_url:
        return "anonymous_facebook_post", post_url, ""
    return "", "", issue or "missing_isolated_resolution_handle"


class _NetworkGuard:
    def __init__(self, *, allow_anonymous_facebook: bool = False) -> None:
        self.meta_requests_blocked = 0
        self.private_requests_blocked = 0
        self.allow_anonymous_facebook = allow_anonymous_facebook
        self._public_cache: dict[str, bool] = {}

    def handle(self, route) -> None:
        try:
            parsed = urlsplit(route.request.url)
            host = (parsed.hostname or "").casefold().rstrip(".")
            if _is_meta_host(host):
                if self._allow_meta_request(route, parsed.path):
                    route.continue_()
                    return
                self.meta_requests_blocked += 1
                route.abort()
                return
            if host:
                is_public = self._public_cache.get(host)
                if is_public is None:
                    is_public = _host_is_public(host)
                    self._public_cache[host] = is_public
                if not is_public:
                    self.private_requests_blocked += 1
                    route.abort()
                    return
            route.continue_()
        except Exception:
            try:
                route.abort()
            except Exception:
                pass

    def _allow_meta_request(self, route, path: str) -> bool:
        if not self.allow_anonymous_facebook:
            return False
        if route.request.resource_type == "document":
            return True
        try:
            frame_host = (
                urlsplit(route.request.frame.url).hostname or ""
            ).casefold()
        except Exception:
            frame_host = ""
        return _is_meta_host(frame_host) or path.casefold().endswith("/l.php")


def _configure_isolated_context(context, network_guard: _NetworkGuard) -> None:
    context.route("**/*", network_guard.handle)
    context.add_init_script(
        """
        (() => {
          const DisabledPeerConnection = function () {
            throw new DOMException(
              "WebRTC disabled in isolated resolver",
              "NotAllowedError"
            );
          };
          Object.defineProperty(window, "RTCPeerConnection", {
            value: DisabledPeerConnection,
            configurable: false,
          });
          Object.defineProperty(window, "webkitRTCPeerConnection", {
            value: DisabledPeerConnection,
            configurable: false,
          });
        })();
        """
    )


def _new_isolated_context(browser):
    options: dict[str, Any] = {
        "accept_downloads": False,
        "service_workers": "block",
    }
    profile_context = browser.contexts[0] if browser.contexts else None
    profile_page = (
        profile_context.pages[0]
        if profile_context is not None and profile_context.pages
        else None
    )
    if profile_page is not None:
        try:
            environment = profile_page.evaluate(
                """
                () => ({
                  userAgent: navigator.userAgent,
                  language: navigator.language,
                  timezone: Intl.DateTimeFormat().resolvedOptions().timeZone,
                  width: Math.max(320, window.innerWidth || 0),
                  height: Math.max(480, window.innerHeight || 0),
                  deviceScaleFactor: Math.max(1, window.devicePixelRatio || 1),
                  touch: Number(navigator.maxTouchPoints || 0) > 0,
                })
                """
            )
            if isinstance(environment, dict):
                options["user_agent"] = environment.get("userAgent")
                options["locale"] = environment.get("language")
                options["timezone_id"] = environment.get("timezone")
                options["viewport"] = {
                    "width": int(environment.get("width") or 390),
                    "height": int(environment.get("height") or 844),
                }
                options["device_scale_factor"] = float(
                    environment.get("deviceScaleFactor") or 1
                )
                options["has_touch"] = bool(environment.get("touch"))
                options["is_mobile"] = bool(
                    environment.get("touch")
                    and re.search(
                        r"android|iphone|mobile",
                        str(environment.get("userAgent") or ""),
                        re.I,
                    )
                )
        except Exception:
            pass
    options = {key: value for key, value in options.items() if value is not None}
    try:
        return browser.new_context(**options)
    except PlaywrightError:
        return browser.new_context(
            accept_downloads=False,
            service_workers="block",
        )


def _resolve_one(
    context,
    raw: dict[str, Any],
    target: str,
    *,
    source: str,
    sequence: int,
    run_dir: Path,
    args,
    network_guard: _NetworkGuard,
    facebook_cookie_count_before: int,
) -> tuple[dict[str, Any], dict[str, Any]]:
    resolved = dict(raw)
    started = time.monotonic()
    blocked_meta_before = network_guard.meta_requests_blocked
    blocked_private_before = network_guard.private_requests_blocked
    result: dict[str, Any] = {
        "status": "pending",
        "cookie_isolated": True,
        "separate_browser_context": True,
        "facebook_cookie_count_before": facebook_cookie_count_before,
        "authenticated_profile_context": False,
        "active_profile_actions_started": False,
        "isolated_navigation_started": False,
        "external_navigation_started": False,
        "anonymous_facebook_navigation_started": False,
        "isolated_click_attempted": False,
        "source": source,
        "target_host": urlsplit(target).hostname,
    }
    page = None
    try:
        page = context.new_page()
        if source == "anonymous_facebook_post":
            _resolve_from_anonymous_facebook_post(
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
            final_url, issue = isolated_external_url(page.url)
            if not final_url:
                raise RuntimeError(f"unsafe landing redirect: {issue}")
            clean, utm, ad_id = facebook_runner.parse_landing(final_url)
            resolved["landing_full"] = final_url
            resolved["landing_clean"] = clean
            resolved["utm"] = utm
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
                    fallback_screenshot_path=(
                        run_dir / screenshot if screenshot else None
                    ),
                )
                if archive:
                    resolved["landing_archive"] = archive
        result["status"] = "completed"
        result["landing_resolved"] = True
        result["landing_screenshot_saved"] = bool(
            resolved.get("landing_screenshot")
        )
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


def _resolve_from_anonymous_facebook_post(
    page,
    context,
    resolved: dict[str, Any],
    result: dict[str, Any],
    post_url: str,
    *,
    sequence: int,
    run_dir: Path,
    args,
) -> None:
    result["isolated_navigation_started"] = True
    result["anonymous_facebook_navigation_started"] = True
    response = page.goto(
        post_url,
        wait_until="domcontentloaded",
        timeout=max(1, args.timeout_ms),
        referer="",
    )
    if response and response.status >= 400:
        raise RuntimeError(f"anonymous Facebook post returned HTTP {response.status}")
    if facebook_runner._facebook_login_required(page):
        raise RuntimeError("anonymous Facebook post requires authentication")

    target = CalibrationTarget(
        url=post_url,
        advertiser=str(resolved.get("advertiser") or ""),
        displayed_domain=str(resolved.get("displayed_domain") or ""),
        headline=str(resolved.get("headline") or ""),
        ad_text=str(resolved.get("ad_text") or ""),
        cta=str(resolved.get("cta") or ""),
        country=_clean(resolved.get("country")),
        fb_ad_id=_clean(resolved.get("fb_ad_id")),
        facebook_page_url=_clean(resolved.get("facebook_page_url")),
        facebook_post_url=post_url,
        landing_clean=_clean(resolved.get("landing_clean")),
        creative_img=_clean(resolved.get("creative_img")),
    )
    located = _wait_for_anonymous_post_cta(
        page,
        target,
        element_id=f"fbspy_isolated_{sequence}",
        timeout_ms=min(max(1, args.timeout_ms), 12_000),
    )
    result["anonymous_post_match"] = located
    if located.get("status") != "located":
        raise RuntimeError(f"anonymous Facebook post not located: {located}")

    element_id = str(located["element_id"])
    ad = facebook_runner.Ad(
        advertiser=target.advertiser,
        ad_type=str(resolved.get("ad_type") or "link"),
        has_video=bool(resolved.get("has_video")),
        country=target.country,
        displayed_domain=target.displayed_domain,
        headline=target.headline,
        ad_text=target.ad_text,
        cta=target.cta,
        cta_href=str(resolved.get("cta_href") or ""),
        creative_img=target.creative_img or "",
        fb_ad_id=target.fb_ad_id,
        feed_element_id=element_id,
        facebook_page_url=target.facebook_page_url,
        facebook_post_url=post_url,
    )
    result["isolated_click_attempted"] = True
    facebook_runner.resolve_in_view(
        page,
        context,
        ad,
        None,
        element_id,
        run_dir,
        debug=None,
        debug_id=sequence,
        feed_url=post_url,
        archive_landing=False,
        landing_archive_timeout=max(1.0, args.landing_ready_seconds),
        landing_archive_max_resources=max(
            1,
            args.landing_archive_max_resources,
        ),
    )
    if not ad.landing_full:
        raise RuntimeError("anonymous Facebook CTA did not resolve an external landing")
    final_url, issue = isolated_external_url(ad.landing_full)
    if not final_url:
        raise RuntimeError(f"unsafe anonymous landing redirect: {issue}")
    clean, utm, ad_id = facebook_runner.parse_landing(final_url)
    resolved["landing_full"] = final_url
    resolved["landing_clean"] = clean
    resolved["utm"] = utm
    resolved["landing_screenshot"] = ad.landing_screenshot
    if ad_id or ad.fb_ad_id:
        resolved["fb_ad_id"] = ad_id or ad.fb_ad_id
    result["external_navigation_started"] = True


def _wait_for_anonymous_post_cta(
    page,
    target: CalibrationTarget,
    *,
    element_id: str,
    timeout_ms: int,
) -> dict[str, Any]:
    started = time.monotonic()
    deadline = started + max(0, timeout_ms) / 1000
    attempts = 0
    last: dict[str, Any] = {"status": "post_not_found"}
    payload = {
        "advertiser": target.advertiser,
        "displayedDomain": target.displayed_domain,
        "headline": target.headline,
        "cta": target.cta,
        "elementId": element_id,
    }
    while True:
        attempts += 1
        try:
            candidate = page.evaluate(_LOCATE_ANONYMOUS_POST_JS, payload)
            if isinstance(candidate, dict):
                last = candidate
        except PlaywrightError as exc:
            last = {
                "status": "locator_error",
                "error": repr(exc),
            }
        waited_ms = round((time.monotonic() - started) * 1000)
        if last.get("status") == "located" or time.monotonic() >= deadline:
            return {
                **last,
                "attempts": attempts,
                "waited_ms": waited_ms,
            }
        page.wait_for_timeout(min(500, max(1, timeout_ms)))


def _reuse_resolution(
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
            source_result.get("source")
            if isinstance(source_result, dict)
            else "reused"
        ),
        "source_row_index": source_row_index,
        "landing_resolved": bool(target.get("landing_full")),
        "landing_screenshot_saved": bool(target.get("landing_screenshot")),
        "landing_archive_saved": bool(target.get("landing_archive")),
        "source_status": (
            source_result.get("status")
            if isinstance(source_result, dict)
            else None
        ),
        "meta_requests_blocked": 0,
        "private_requests_blocked": 0,
    }


def _is_meta_host(host: str) -> bool:
    return any(
        host == suffix or host.endswith(f".{suffix}")
        for suffix in _META_HOST_SUFFIXES
    )


def _valid_facebook_post_url(value: Any) -> str:
    candidate = str(value or "").strip()
    if not candidate:
        return ""
    try:
        parsed = urlsplit(candidate)
    except ValueError:
        return ""
    host = (parsed.hostname or "").casefold()
    if host != "facebook.com" and not host.endswith(".facebook.com"):
        return ""
    parts = [part for part in parsed.path.split("/") if part]
    if (
        "posts" in parts
        or parsed.path.rstrip("/").endswith(("story.php", "permalink.php"))
    ):
        return candidate
    return ""


def _host_is_public(host: str) -> bool:
    normalized = host.casefold().rstrip(".")
    if (
        not normalized
        or normalized == "localhost"
        or normalized.endswith(_LOCAL_HOST_SUFFIXES)
    ):
        return False
    try:
        addresses = {item[4][0] for item in socket.getaddrinfo(normalized, None)}
    except OSError:
        return False
    if not addresses:
        return False
    try:
        return all(ipaddress.ip_address(address).is_global for address in addresses)
    except ValueError:
        return False


def _summary(rows: list[dict[str, Any]], *, status: str) -> dict[str, Any]:
    held = [row for row in rows if row.get("relevance_gate") == "hold"]
    results = [
        row.get("isolated_resolution")
        for row in held
        if isinstance(row.get("isolated_resolution"), dict)
    ]
    resolved_statuses = {"completed", "reused_isolated_result"}
    isolation_violations = sum(
        bool(item.get("isolated_navigation_started"))
        and (
            item.get("cookie_isolated") is not True
            or item.get("separate_browser_context") is not True
            or item.get("facebook_cookie_count_before") != 0
            or item.get("authenticated_profile_context") is not False
            or bool(item.get("active_profile_actions_started"))
        )
        for item in results
    )
    return {
        "status": status,
        "finished_at": facebook_runner.utc_now(),
        "total": len(rows),
        "held": len(held),
        "resolved": sum(
            item.get("status") in resolved_statuses
            and bool(item.get("landing_resolved"))
            and bool(item.get("landing_screenshot_saved"))
            for item in results
        ),
        "unresolved": sum(
            not (
                item.get("status") in resolved_statuses
                and bool(item.get("landing_resolved"))
                and bool(item.get("landing_screenshot_saved"))
            )
            for item in results
        ),
        "external_navigations": sum(
            bool(item.get("external_navigation_started")) for item in results
        ),
        "anonymous_facebook_navigations": sum(
            bool(item.get("anonymous_facebook_navigation_started"))
            for item in results
        ),
        "isolated_click_attempts": sum(
            bool(item.get("isolated_click_attempted")) for item in results
        ),
        "meta_requests_blocked": sum(
            int(item.get("meta_requests_blocked") or 0) for item in results
        ),
        "private_requests_blocked": sum(
            int(item.get("private_requests_blocked") or 0) for item in results
        ),
        "authenticated_profile_actions_started": sum(
            bool(item.get("active_profile_actions_started")) for item in results
        ),
        "isolation_violations": isolation_violations,
    }


def _clean(value: Any) -> str | None:
    candidate = str(value or "").strip()
    return candidate or None


def _load_ads(path: Path) -> list[dict[str, Any]]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, list):
        raise ValueError(f"Expected a JSON list: {path}")
    return [dict(item) for item in payload if isinstance(item, dict)]


def _write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, default=str),
        encoding="utf-8",
    )
    tmp.replace(path)


def _append_event(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(payload, ensure_ascii=False, default=str) + "\n")


if __name__ == "__main__":
    raise SystemExit(main())

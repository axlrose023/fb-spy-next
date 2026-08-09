from __future__ import annotations

import time
from pathlib import Path
from typing import Any

from playwright.sync_api import Error as PlaywrightError

from app.facebook.calibration import CalibrationTarget
from app.facebook.navigation import facebook_login_required
from app.services import facebook_runner

from ..evidence.policy import isolated_external_url
from .isolation import host_is_public

LOCATE_ANONYMOUS_POST_JS = r"""
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


def resolve_from_anonymous_post(
    page: Any,
    context: Any,
    resolved: dict[str, Any],
    result: dict[str, Any],
    post_url: str,
    *,
    sequence: int,
    run_dir: Path,
    args: Any,
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
    if facebook_login_required(page):
        raise RuntimeError("anonymous Facebook post requires authentication")

    target = _calibration_target(resolved, post_url)
    located = wait_for_anonymous_post_cta(
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
        landing_archive_max_resources=max(1, args.landing_archive_max_resources),
    )
    if not ad.landing_full:
        raise RuntimeError("anonymous Facebook CTA did not resolve an external landing")
    final_url, issue = isolated_external_url(
        ad.landing_full,
        host_is_public=host_is_public,
    )
    if not final_url:
        raise RuntimeError(f"unsafe anonymous landing redirect: {issue}")
    clean, utm, ad_id = facebook_runner.parse_landing(final_url)
    resolved.update(
        {
            "landing_full": final_url,
            "landing_clean": clean,
            "utm": utm,
            "landing_screenshot": ad.landing_screenshot,
        }
    )
    if ad_id or ad.fb_ad_id:
        resolved["fb_ad_id"] = ad_id or ad.fb_ad_id
    result["external_navigation_started"] = True


def wait_for_anonymous_post_cta(
    page: Any,
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
            candidate = page.evaluate(LOCATE_ANONYMOUS_POST_JS, payload)
            if isinstance(candidate, dict):
                last = candidate
        except PlaywrightError as exc:
            last = {"status": "locator_error", "error": repr(exc)}
        waited_ms = round((time.monotonic() - started) * 1000)
        if last.get("status") == "located" or time.monotonic() >= deadline:
            return {**last, "attempts": attempts, "waited_ms": waited_ms}
        page.wait_for_timeout(min(500, max(1, timeout_ms)))


def _calibration_target(raw: dict[str, Any], post_url: str) -> CalibrationTarget:
    return CalibrationTarget(
        url=post_url,
        advertiser=str(raw.get("advertiser") or ""),
        displayed_domain=str(raw.get("displayed_domain") or ""),
        headline=str(raw.get("headline") or ""),
        ad_text=str(raw.get("ad_text") or ""),
        cta=str(raw.get("cta") or ""),
        country=_clean(raw.get("country")),
        fb_ad_id=_clean(raw.get("fb_ad_id")),
        facebook_page_url=_clean(raw.get("facebook_page_url")),
        facebook_post_url=post_url,
        landing_clean=_clean(raw.get("landing_clean")),
        creative_img=_clean(raw.get("creative_img")),
    )


def _clean(value: Any) -> str | None:
    candidate = str(value or "").strip()
    return candidate or None

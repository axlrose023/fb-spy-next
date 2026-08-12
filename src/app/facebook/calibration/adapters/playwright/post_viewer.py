from __future__ import annotations

import time
from typing import Any, cast
from urllib.parse import parse_qs, urlsplit
from uuid import uuid4

from playwright.sync_api import Page

from ...planning.target_pool import CalibrationTarget


def locate_saved_post(page: Page, target: CalibrationTarget) -> dict[str, Any]:
    post_url = target.facebook_post_url or target.url
    post_id = _post_id(post_url)
    if not post_id:
        return {"status": "invalid_post_url", "url": post_url}
    element_id = f"fbspy_saved_{uuid4().hex}"
    return cast(
        dict[str, Any],
        page.evaluate(
            _LOCATE_SAVED_POST_JS,
            {
                "postId": post_id,
                "advertiser": target.advertiser,
                "displayedDomain": target.displayed_domain,
                "headline": target.headline,
                "adText": target.ad_text,
                "elementId": element_id,
            },
        ),
    )


def wait_for_saved_post(
    page: Page,
    target: CalibrationTarget,
    *,
    timeout_ms: int = 12_000,
    poll_ms: int = 500,
) -> dict[str, Any]:
    """Wait for Facebook's mobile shell to render the requested deep link."""
    started = time.monotonic()
    deadline = started + max(0, timeout_ms) / 1000
    last: dict[str, Any] = {"status": "post_not_found"}
    attempts = 0
    while True:
        attempts += 1
        try:
            last = locate_saved_post(page, target)
        except Exception as exc:
            last = {"status": "locate_error", "error": repr(exc)}
        if last.get("status") == "located" or time.monotonic() >= deadline:
            return {
                **last,
                "attempts": attempts,
                "waited_ms": round((time.monotonic() - started) * 1000),
            }
        page.wait_for_timeout(max(50, min(poll_ms, timeout_ms)))


def view_feed_ad(page: Page, element_id: str, seconds: float) -> dict[str, Any]:
    located = cast(
        dict[str, Any],
        page.evaluate(
            _VIEW_AD_JS,
            {"elementId": element_id},
        ),
    )
    if located.get("status") != "viewing":
        return located
    deadline = time.monotonic() + max(0.0, seconds)
    while time.monotonic() < deadline:
        time.sleep(min(1.0, deadline - time.monotonic()))
    return located


def _post_id(url: str) -> str:
    try:
        parsed = urlsplit(url)
    except ValueError:
        return ""
    parts = [part for part in parsed.path.split("/") if part]
    if "posts" in parts:
        index = parts.index("posts")
        if index + 1 < len(parts):
            return parts[index + 1]
    return (parse_qs(parsed.query).get("story_fbid") or [""])[0]


_VIEW_AD_JS = r"""
({elementId}) => {
  const root = document.querySelector(`[data-fbspy-id="${elementId}"]`);
  if (!root) return {status: "root_not_found"};
  root.scrollIntoView({block: "center", inline: "nearest"});
  const video = root.querySelector("video");
  if (video) {
    video.muted = true;
    Promise.resolve(video.play()).catch(() => {});
  }
  return {status: "viewing", has_video: !!video};
}
"""


_LOCATE_SAVED_POST_JS = r"""
({postId, advertiser, displayedDomain, headline, adText, elementId}) => {
  const norm = value => (value || "").toLocaleLowerCase().replace(/\s+/g, " ").trim();
  const expectedAdvertiser = norm(advertiser);
  const expectedSignals = [displayedDomain, headline, adText]
    .map(norm).filter(value => value.length >= 4);
  const controls = root => [...root.querySelectorAll('button,[role="button"]')]
    .map(el => norm(`${el.getAttribute("aria-label") || ""} ${el.innerText || ""}`));
  const isPostRoot = (root, requireSignal) => {
    const labels = controls(root);
    const hasLike = labels.some(label => ["like", "me gusta", "beğen", "j’aime"]
      .some(term => label.includes(norm(term))));
    const hasComment = labels.some(label => ["comment", "comentario", "comentar", "yorum"]
      .some(term => label.includes(norm(term))));
    if (!hasLike || !hasComment) return false;
    const text = norm(root.innerText);
    if (expectedAdvertiser && !text.includes(expectedAdvertiser)) return false;
    if (requireSignal && expectedSignals.length &&
        !expectedSignals.some(signal => text.includes(signal))) return false;
    const rect = root.getBoundingClientRect();
    return rect.width >= 280 && rect.height >= 120;
  };
  const rootFor = (seed, requireSignal) => {
    for (let root = seed; root && root !== document.body; root = root.parentElement) {
      if (root.tagName === "DIV" && isPostRoot(root, requireSignal)) return root;
    }
    return null;
  };
  const containsPostId = el => {
    for (const attr of el.attributes || []) {
      const value = attr.value || "";
      if (!value.includes(postId)) continue;
      if (/top_level_post_id|story_fbid|post_id|mf_objid/.test(value)) return true;
    }
    return false;
  };

  let root = null;
  let strategy = null;
  for (const el of document.querySelectorAll("*")) {
    if (!containsPostId(el)) continue;
    root = rootFor(el, expectedSignals.length > 0);
    if (root) {
      strategy = "post_id";
      break;
    }
  }
  if (!root) {
    const commentControls = [...document.querySelectorAll('button,[role="button"]')]
      .filter(el => ["comment", "comentario", "comentar", "yorum"]
        .some(term => norm(`${el.getAttribute("aria-label") || ""} ${el.innerText || ""}`).includes(norm(term))));
    for (const control of commentControls) {
      root = rootFor(control, true);
      if (root) {
        strategy = expectedSignals.length ? "metadata" : "advertiser";
        break;
      }
    }

    // Advertiser-only matching is safe only for legacy targets that have no
    // saved creative metadata. Advertisers can reuse a post for an unrelated
    // offer, so a unique name must not override conflicting saved evidence.
    if (!root && expectedAdvertiser && !expectedSignals.length) {
      const advertiserRoots = [];
      const seenRoots = new Set();
      const advertiserSeeds = [
        ...document.querySelectorAll('a,[role="link"],span,strong,h1,h2,h3'),
      ].filter(el => norm(el.innerText) === expectedAdvertiser);
      for (const seed of advertiserSeeds) {
        const candidate = rootFor(seed, false);
        if (!candidate || seenRoots.has(candidate)) continue;
        seenRoots.add(candidate);
        advertiserRoots.push(candidate);
      }
      if (advertiserRoots.length === 1) {
        root = advertiserRoots[0];
        strategy = "advertiser_unique";
      }
    }
  }
  if (!root) return {
    status: "post_not_found",
    post_id: postId,
    advertiser_in_page: expectedAdvertiser
      ? norm(document.body.innerText).includes(expectedAdvertiser)
      : false,
  };
  root.dataset.fbspyId = elementId;
  root.scrollIntoView({block: "center", inline: "nearest"});
  return {
    status: "located",
    element_id: elementId,
    post_id: postId,
    advertiser,
    strategy,
  };
}
"""

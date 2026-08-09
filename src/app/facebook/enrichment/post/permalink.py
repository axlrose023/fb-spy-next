from __future__ import annotations

import time
from typing import Any, Protocol

from app.facebook.collection import CollectedAd
from app.facebook.navigation import is_facebook_feed_url, recover_facebook_feed

from .urls import facebook_post_identity_from_url, normalized_facebook_post_url

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


class DebugRecorderPort(Protocol):
    def event(self, kind: str, **payload: Any) -> None: ...


def resolve_facebook_post_url(
    page: Any,
    ad: CollectedAd,
    element_id: str | None,
    *,
    feed_url: str = "https://m.facebook.com/",
    debug: DebugRecorderPort | None = None,
    debug_id: int = 0,
) -> bool:
    """Open comments read-only to recover a direct post URL from a feed ad."""
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
            identity = facebook_post_identity_from_url(page.url)
            if identity:
                break
            page.wait_for_timeout(250)
        if not identity:
            page.keyboard.press("Escape")
            return False
        owner_id, _post_id = identity
        observed_post_url = normalized_facebook_post_url(page.url)
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
            if not is_facebook_feed_url(page.url):
                page.go_back(wait_until="domcontentloaded", timeout=12000)
                page.wait_for_timeout(750)
        except Exception:
            pass
        recover_facebook_feed(page, feed_url=feed_url)

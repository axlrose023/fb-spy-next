from __future__ import annotations

from typing import Any, cast
from uuid import uuid4

from playwright.sync_api import Page

from ...execution.matching import similarity as _similarity
from .reaction import _trusted_click, _wait_for_active_state


def follow_advertiser(
    page: Page,
    element_id: str,
    advertiser: str,
    *,
    timeout_ms: int = 15_000,
) -> dict[str, Any]:
    feed_url = page.url
    advertiser_marker = uuid4().hex
    opened = cast(
        dict[str, Any],
        page.evaluate(
            _OPEN_ADVERTISER_JS,
            {
                "elementId": element_id,
                "advertiser": advertiser,
                "marker": advertiser_marker,
            },
        ),
    )
    if opened.get("status") != "located":
        return opened
    _trusted_click(page, advertiser_marker, timeout_ms=timeout_ms)
    opened["status"] = "clicked"

    page.wait_for_timeout(1500)
    try:
        page.wait_for_load_state("domcontentloaded", timeout=timeout_ms)
    except Exception:
        pass
    if page.url == feed_url:
        return {"status": "advertiser_navigation_failed", "control": opened}

    result: dict[str, Any]
    try:
        title = page.title()
        if _similarity(title, advertiser) < 0.55:
            result = {
                "status": "advertiser_mismatch",
                "title": title,
                "url": page.url,
            }
        else:
            marker = uuid4().hex
            result = cast(
                dict[str, Any],
                page.evaluate(
                    _CLICK_GLOBAL_CONTROL_JS,
                    {
                        "positive": ["follow", "seguir", "takip et"],
                        "expectedTarget": advertiser,
                        "marker": marker,
                        "negative": [
                            "following",
                            "siguiendo",
                            "takip ediliyor",
                            "takiptesin",
                            "unfollow",
                            "dejar de seguir",
                        ],
                    },
                ),
            )
            if result.get("status") == "located":
                _trusted_click(page, marker, timeout_ms=timeout_ms)
                result["status"] = "clicked"
            result["url"] = page.url
            result["title"] = title
            if result.get("status") == "clicked":
                confirmation = _wait_for_active_state(
                    page,
                    _READ_GLOBAL_CONTROL_STATE_JS,
                    {
                        "active": [
                            "following",
                            "siguiendo",
                            "takip ediliyor",
                            "takiptesin",
                            "unfollow",
                            "dejar de seguir",
                        ],
                    },
                    timeout_ms=min(10_000, timeout_ms),
                )
                if confirmation.get("status") == "active":
                    result["confirmed"] = True
                    result["confirmation"] = confirmation
                else:
                    result = {
                        "status": "click_unconfirmed",
                        "action": "follow",
                        "click": result,
                        "confirmation": confirmation,
                        "url": page.url,
                        "title": title,
                    }
    finally:
        try:
            page.go_back(wait_until="domcontentloaded", timeout=timeout_ms)
            page.wait_for_timeout(500)
        except Exception:
            try:
                page.goto(feed_url, wait_until="domcontentloaded", timeout=timeout_ms)
            except Exception:
                pass
    return result


_OPEN_ADVERTISER_JS = r"""
({elementId, advertiser, marker}) => {
  const root = document.querySelector(`[data-fbspy-id="${elementId}"]`);
  if (!root) return {status: "root_not_found", action: "advertiser"};
  const norm = value => (value || "").toLocaleLowerCase().replace(/\s+/g, " ").trim();
  const expected = norm(advertiser);
  const links = [...root.querySelectorAll('a,[role="link"]')];
  const target = links.find(el => norm(el.innerText) === expected);
  if (!target) return {status: "advertiser_control_not_found", action: "advertiser"};
  root.scrollIntoView({block: "center", inline: "nearest"});
  target.setAttribute("data-fbspy-action-control", marker);
  return {status: "located", action: "advertiser", label: advertiser};
}
"""


_CLICK_GLOBAL_CONTROL_JS = r"""
({positive, negative, expectedTarget, marker}) => {
  const norm = value => (value || "").toLocaleLowerCase().replace(/\s+/g, " ").trim();
  const expected = norm(expectedTarget);
  const controls = [...document.querySelectorAll('button,[role="button"]')];
  for (const el of controls) {
    const rect = el.getBoundingClientRect();
    if (rect.width < 20 || rect.height < 16) continue;
    const values = [norm(el.getAttribute("aria-label")), norm(el.innerText)].filter(Boolean);
    const label = values.join(" ");
    if (!label) continue;
    if (negative.some(term => label === norm(term) || label.includes(norm(term)))) {
      return {status: "already_active", action: "follow", label};
    }
    const matches = values.some(value => positive.some(term => {
      const wanted = norm(term);
      if (value === wanted || value.endsWith(` ${wanted}`)) return true;
      return expected && value.startsWith(`${wanted} `) && value.includes(expected);
    }));
    if (matches) {
      el.setAttribute("data-fbspy-action-control", marker);
      return {status: "located", action: "follow", label};
    }
  }
  return {status: "control_not_found", action: "follow"};
}
"""


_READ_GLOBAL_CONTROL_STATE_JS = r"""
({active}) => {
  const norm = value => (value || "").toLocaleLowerCase().replace(/\s+/g, " ").trim();
  const controls = [...document.querySelectorAll('button,[role="button"]')];
  for (const el of controls) {
    const rect = el.getBoundingClientRect();
    if (rect.width < 20 || rect.height < 16) continue;
    const label = norm(`${el.getAttribute("aria-label") || ""} ${el.innerText || ""}`);
    if (active.some(term => label.includes(norm(term)))) {
      return {status: "active", label};
    }
  }
  return {status: "inactive"};
}
"""

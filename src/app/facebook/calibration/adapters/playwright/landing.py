from __future__ import annotations

import time
from typing import Any
from urllib.parse import parse_qs, urlsplit
from uuid import uuid4

from playwright.sync_api import Error as PlaywrightError
from playwright.sync_api import Page

from ...execution.matching import normalized_domain as _domain
from .reaction import _trusted_click


def open_ad_landing(
    page: Page,
    element_id: str,
    *,
    cta: str = "",
    expected_url: str = "",
    timeout_ms: int = 20_000,
) -> tuple[dict[str, Any], Page | None, list[Page]]:
    """Open one ad CTA and return ownership of any new pages to the caller."""
    marker = uuid4().hex
    located = page.evaluate(
        _LOCATE_LANDING_CONTROL_JS,
        {
            "elementId": element_id,
            "cta": cta,
            "expectedUrl": expected_url,
            "marker": marker,
        },
    )
    if located.get("status") != "located":
        return located, None, []

    context = page.context
    existing_pages = set(context.pages)
    source_url = page.url
    _trusted_click(page, marker, timeout_ms=min(max(1, timeout_ms), 8_000))

    deadline = time.monotonic() + max(0, timeout_ms) / 1000
    landing_page = None
    landing_url = ""
    while time.monotonic() < deadline:
        candidates = [
            candidate
            for candidate in context.pages
            if (candidate is page or candidate not in existing_pages)
            and not candidate.url.startswith("devtools://")
        ]
        candidates.sort(key=lambda candidate: candidate is page)
        for candidate in candidates:
            external = _external_url(candidate.url)
            if external:
                landing_page = candidate
                landing_url = external
                break
        if landing_page is not None:
            break
        page.wait_for_timeout(250)

    opened_pages = [
        candidate for candidate in context.pages if candidate not in existing_pages
    ]
    if landing_page is None:
        for candidate in opened_pages:
            try:
                candidate.close(run_before_unload=False)
            except PlaywrightError:
                pass
        return (
            {
                **located,
                "status": "navigation_not_observed",
                "source_url": source_url,
            },
            None,
            [],
        )

    load_error = None
    try:
        remaining_ms = max(1, round((deadline - time.monotonic()) * 1000))
        landing_page.wait_for_load_state(
            "domcontentloaded",
            timeout=remaining_ms,
        )
    except PlaywrightError as exc:
        load_error = repr(exc)

    try:
        title = landing_page.title().strip()
    except PlaywrightError:
        title = ""

    expected_domain = _domain(expected_url)
    final_domain = _domain(landing_url)
    result = {
        **located,
        "status": "visited",
        "source_url": source_url,
        "landing_url": landing_url,
        "landing_domain": final_domain,
        "expected_domain": expected_domain,
        "expected_domain_match": bool(
            expected_domain
            and final_domain
            and (
                final_domain == expected_domain
                or final_domain.endswith(f".{expected_domain}")
                or expected_domain.endswith(f".{final_domain}")
            )
        ),
        "opened_new_page": landing_page is not page,
        "title": title,
    }
    if load_error:
        result["load_error"] = load_error

    return result, landing_page, opened_pages


def visit_ad_landing(
    page: Page,
    element_id: str,
    *,
    cta: str = "",
    expected_url: str = "",
    dwell_seconds: float = 10.0,
    timeout_ms: int = 20_000,
) -> dict[str, Any]:
    """Open one ad CTA in the current Octo context and close its new tab."""
    result, landing_page, opened_pages = open_ad_landing(
        page,
        element_id,
        cta=cta,
        expected_url=expected_url,
        timeout_ms=timeout_ms,
    )
    if landing_page is None:
        return result

    if dwell_seconds > 0:
        landing_page.wait_for_timeout(round(dwell_seconds * 1000))
    result["dwell_seconds"] = max(0.0, dwell_seconds)

    for candidate in opened_pages:
        try:
            candidate.close(run_before_unload=False)
        except PlaywrightError:
            pass
    return result


def _external_url(value: Any) -> str:
    url = str(value or "").strip()
    try:
        parsed = urlsplit(url)
    except ValueError:
        return ""
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        return ""
    host = parsed.hostname.casefold().removeprefix("www.")
    facebook_hosts = ("facebook.com", "fb.com", "messenger.com")
    if not any(host == item or host.endswith(f".{item}") for item in facebook_hosts):
        return url
    if host == "l.facebook.com" and parsed.path.rstrip("/").endswith("/l.php"):
        target = (parse_qs(parsed.query).get("u") or [""])[0]
        return _external_url(target)
    return ""


_LOCATE_LANDING_CONTROL_JS = r"""
({elementId, cta, expectedUrl, marker}) => {
  const root = document.querySelector(`[data-fbspy-id="${elementId}"]`);
  if (!root) return {status: "root_not_found", action: "landing_visit"};
  const norm = value => (value || "").toLocaleLowerCase()
    .replace(/\s+/g, " ").trim();
  const expected = norm(cta);
  let expectedHost = "";
  try { expectedHost = new URL(expectedUrl).hostname.replace(/^www\./, ""); }
  catch (_) {}
  const positive = [
    "learn more", "get offer", "get started", "sign up", "register",
    "shop now", "buy now", "order now", "apply now", "book now",
    "download", "contact us", "visit website", "whatsapp",
    "más información", "mas información", "más detalles", "registrarte",
    "registrarse", "comprar", "comprar ahora", "ir al sitio web",
    "daha fazla bilgi", "daha fazla bilgi al", "teklifi al",
    "şimdi alışveriş yap", "şimdi sipariş ver", "şimdi rezervasyon yap",
    "kayıt ol", "başvur"
  ];
  const excluded = [
    "like", "unlike", "comment", "share", "follow", "following",
    "me gusta", "comentar", "compartir", "seguir", "beğen", "yorum",
    "paylaş", "takip", "more options", "comments and reactions"
  ];
  const visible = el => {
    const rect = el.getBoundingClientRect();
    const style = getComputedStyle(el);
    return rect.width >= 32 && rect.height >= 16 && rect.right > 0
      && rect.left < innerWidth && style.visibility !== "hidden"
      && style.display !== "none";
  };
  const controls = [...root.querySelectorAll(
    'a,button,[role="button"],[role="link"],[data-action-id],[tabindex="0"]'
  )];
  let best = null;
  for (const el of controls) {
    if (!visible(el)) continue;
    const label = norm(
      `${el.getAttribute("aria-label") || ""} ${el.innerText || ""}`
    );
    if (excluded.some(term => label.includes(term))) continue;
    let score = 0;
    if (expected && label === expected) score += 180;
    else if (expected && label.includes(expected)) score += 100;
    if (positive.some(term => label === term)) score += 120;
    else if (positive.some(term => label.includes(term))) score += 60;
    const href = el.href || el.getAttribute("href") || "";
    if (href) {
      try {
        const host = new URL(href, location.href).hostname.replace(/^www\./, "");
        if (host && !host.endsWith("facebook.com")) score += 40;
        if (expectedHost && (host === expectedHost || host.endsWith(`.${expectedHost}`))) {
          score += 120;
        }
      } catch (_) {}
    }
    if (!score) continue;
    const rect = el.getBoundingClientRect();
    score += Math.max(0, Math.min(20, Math.round(rect.width / 20)));
    score -= Math.min(50, Math.round(label.length / 12));
    if (!best || score > best.score || (score === best.score && rect.left < best.left)) {
      best = {el, score, left: rect.left, label, href};
    }
  }
  if (!best) return {
    status: "control_not_found",
    action: "landing_visit",
    expected_cta: expected,
    expected_domain: expectedHost,
  };
  best.el.scrollIntoView({block: "center", inline: "nearest"});
  best.el.setAttribute("data-fbspy-action-control", marker);
  return {
    status: "located",
    action: "landing_visit",
    label: best.label,
    href: best.href,
    expected_cta: expected,
    expected_domain: expectedHost,
  };
}
"""

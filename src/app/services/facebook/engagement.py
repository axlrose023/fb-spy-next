from __future__ import annotations

import re
import time
from dataclasses import dataclass
from difflib import SequenceMatcher
from typing import Any
from urllib.parse import parse_qs, urlsplit
from uuid import uuid4

from playwright.sync_api import Error as PlaywrightError
from playwright.sync_api import Page

from app.services.facebook.calibration import CalibrationTarget


@dataclass(frozen=True, slots=True)
class EngagementPolicy:
    reaction_rate: float = 0.65
    follow_rate: float = 0.20
    comment_every: int = 2
    max_reactions: int = 6
    max_follows: int = 2
    max_comments: int = 5
    min_interactions: int = 1


def find_matching_target(
    row: dict[str, Any],
    targets: list[CalibrationTarget],
) -> tuple[CalibrationTarget | None, int]:
    best_target = None
    best_score = 0
    for target in targets:
        score = target_match_score(row, target)
        if score > best_score:
            best_target = target
            best_score = score
    return (best_target, best_score) if best_score >= 12 else (None, best_score)


def target_match_score(row: dict[str, Any], target: CalibrationTarget) -> int:
    element_id = str(row.get("element_id") or "")
    if target.feed_element_id and element_id == target.feed_element_id:
        return 100

    row_domain = _domain(row.get("domain"))
    target_domain = _domain(target.displayed_domain or target.landing_clean or target.url)
    domain_match = bool(row_domain and target_domain and row_domain == target_domain)
    row_advertiser = _text(row.get("advertiser"))
    target_advertiser = _text(target.advertiser)
    advertiser_match = bool(
        row_advertiser
        and target_advertiser
        and row_advertiser == target_advertiser
    )
    headline_similarity = _similarity(row.get("headline"), target.headline)
    body_similarity = _similarity(row.get("ad_text"), target.ad_text)

    score = 12 if domain_match else 0
    score += 7 if advertiser_match else 0
    score += 6 if headline_similarity >= 0.80 else 0
    score += 4 if body_similarity >= 0.75 else 0
    return score


def live_ad_key(row: dict[str, Any]) -> str:
    values = (
        row.get("advertiser"),
        row.get("domain"),
        row.get("headline"),
        row.get("ad_text"),
        row.get("creative_img"),
    )
    return "\x1f".join(_text(value) for value in values)


def click_like(page: Page, element_id: str) -> dict[str, Any]:
    result = _click_scoped_control(
        page,
        element_id=element_id,
        action="reaction",
        positive=["like", "me gusta", "beğen", "j’aime", "gefällt mir"],
        negative=[
            "unlike",
            "remove like",
            "ya no me gusta",
            "retirar me gusta",
            "beğenmekten vazgeç",
            "likepressed",
            "me gustapressed",
            "beğenpressed",
        ],
        exclude=[
            "comment",
            "comentario",
            "yorum",
            "share",
            "compartir",
            "paylaş",
            "han reaccionado",
            "have reacted",
        ],
    )
    if result.get("status") == "clicked":
        confirmation = _wait_for_active_state(
            page,
            _READ_SCOPED_CONTROL_STATE_JS,
            {
                "elementId": element_id,
                "active": [
                    "unlike",
                    "remove like",
                    "ya no me gusta",
                    "retirar me gusta",
                    "beğenmekten vazgeç",
                    "likepressed",
                    "me gustapressed",
                    "beğenpressed",
                ],
            },
            timeout_ms=8000,
        )
        if confirmation.get("status") == "active":
            result["confirmed"] = True
            result["confirmation"] = confirmation
        else:
            result = {
                "status": "click_unconfirmed",
                "action": "reaction",
                "click": result,
                "confirmation": confirmation,
            }
    return result


def post_comment(page: Page, element_id: str, text: str) -> dict[str, Any]:
    opened = _click_scoped_control(
        page,
        element_id=element_id,
        action="comment",
        positive=["comment", "comentario", "comentar", "yorum"],
        negative=[],
        exclude=[
            "comments and reactions",
            "comentarios y reacciones",
            "people reacted",
            "people have reacted",
            "personas han reaccionado",
        ],
    )
    if opened.get("status") != "clicked":
        return opened
    composer, composer_scope = _wait_for_comment_composer(
        page,
        element_id,
        timeout_ms=5000,
    )
    if composer is None:
        return {"status": "composer_not_found", "control": opened}
    before_count = page.evaluate(_COUNT_EXACT_TEXT_JS, text)
    composer.fill(text)
    marker = uuid4().hex
    submit = composer.evaluate(
        _LOCATE_COMMENT_SUBMIT_JS,
        {
            "marker": marker,
            "positive": [
                "post comment",
                "publish comment",
                "send comment",
                "post",
                "send",
                "publicar comentario",
                "publicar comentário",
                "publicar",
                "enviar",
                "yorum paylaş",
                "gönder",
                "paylaş",
                "i-post",
                "publier le commentaire",
                "kommentar posten",
            ],
        },
    )
    if submit.get("status") == "located":
        _trusted_click(page, marker, timeout_ms=8000)
    else:
        try:
            composer.press("Enter")
            submit = {
                "status": "keyboard_submitted",
                "action": "comment_submit",
            }
        except Exception as exc:
            composer.fill("")
            return {
                "status": "submit_control_not_found",
                "control": opened,
                "submit": submit,
                "keyboard_error": repr(exc),
            }
    confirmed = False
    remaining = text
    for _ in range(60):
        page.wait_for_timeout(500)
        try:
            remaining = (
                composer.input_value()
                if composer.evaluate("el => el.tagName") == "TEXTAREA"
                else composer.inner_text()
            )
        except Exception:
            remaining = ""
        state = page.evaluate(_COMMENT_SUBMISSION_STATE_JS, text)
        if (
            not remaining.strip()
            and state.get("count", 0) > before_count
            and not state.get("pending")
        ):
            confirmed = True
            break
    if not confirmed:
        try:
            if remaining.strip():
                composer.fill("")
        except Exception:
            pass
        state = page.evaluate(_COMMENT_SUBMISSION_STATE_JS, text)
        return {
            "status": "submit_unconfirmed",
            "control": opened,
            "submit": submit,
            "composer_scope": composer_scope,
            "composer_remaining": remaining.strip(),
            "before_count": before_count,
            "after_count": state.get("count", 0),
            "pending": bool(state.get("pending")),
        }
    return {
        "status": "posted",
        "text": text,
        "control": opened,
        "submit": submit,
        "composer_scope": composer_scope,
    }


def locate_saved_post(page: Page, target: CalibrationTarget) -> dict[str, Any]:
    post_url = target.facebook_post_url or target.url
    post_id = _post_id(post_url)
    if not post_id:
        return {"status": "invalid_post_url", "url": post_url}
    element_id = f"fbspy_saved_{uuid4().hex}"
    return page.evaluate(
        _LOCATE_SAVED_POST_JS,
        {
            "postId": post_id,
            "advertiser": target.advertiser,
            "displayedDomain": target.displayed_domain,
            "headline": target.headline,
            "adText": target.ad_text,
            "elementId": element_id,
        },
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


def follow_advertiser(
    page: Page,
    element_id: str,
    advertiser: str,
    *,
    timeout_ms: int = 15_000,
) -> dict[str, Any]:
    feed_url = page.url
    advertiser_marker = uuid4().hex
    opened = page.evaluate(
        _OPEN_ADVERTISER_JS,
        {
            "elementId": element_id,
            "advertiser": advertiser,
            "marker": advertiser_marker,
        },
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
            result = page.evaluate(
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


def view_feed_ad(page: Page, element_id: str, seconds: float) -> dict[str, Any]:
    located = page.evaluate(
        _VIEW_AD_JS,
        {"elementId": element_id},
    )
    if located.get("status") != "viewing":
        return located
    deadline = time.monotonic() + max(0.0, seconds)
    while time.monotonic() < deadline:
        time.sleep(min(1.0, deadline - time.monotonic()))
    return located


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

    opened_pages = [candidate for candidate in context.pages if candidate not in existing_pages]
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


def _first_visible(scope, selector: str):
    for locator in scope.locator(selector).all():
        try:
            if locator.is_visible():
                return locator
        except Exception:
            continue
    return None


def _wait_for_comment_composer(
    page: Page,
    element_id: str,
    *,
    timeout_ms: int,
):
    deadline = time.monotonic() + max(0, timeout_ms) / 1000
    while True:
        root = page.locator(f'[data-fbspy-id="{element_id}"]').first
        composer = _first_visible(root, _COMMENT_COMPOSER_SELECTOR)
        if composer is not None:
            return composer, "post"
        composer = _first_visible(page, _COMMENT_COMPOSER_SELECTOR)
        if composer is not None:
            return composer, "comments_screen"
        if time.monotonic() >= deadline:
            return None, "not_found"
        page.wait_for_timeout(250)


_COMMENT_COMPOSER_SELECTOR = (
    "textarea, [contenteditable='true'][role='textbox'], "
    "[contenteditable='true'][role='combobox']"
)

_COUNT_EXACT_TEXT_JS = r"""
text => {
  const value = String(text || "");
  if (!value) return 0;
  const haystack = document.body?.innerText || "";
  return haystack.split(value).length - 1;
}
"""

_COMMENT_SUBMISSION_STATE_JS = r"""
text => {
  const value = String(text || "");
  const haystack = document.body?.innerText || "";
  const folded = haystack.toLocaleLowerCase();
  const pendingTerms = [
    "posting", "sending", "publicando", "enviando", "paylaşılıyor",
    "publication en cours", "wird gepostet",
  ];
  return {
    count: value ? haystack.split(value).length - 1 : 0,
    pending: pendingTerms.some(term => folded.includes(term)),
  };
}
"""

_LOCATE_COMMENT_SUBMIT_JS = r"""
(composer, {marker, positive}) => {
  const norm = value => (value || "").toLocaleLowerCase()
    .replace(/\s+/g, " ").trim();
  const wanted = positive.map(norm);
  for (let root = composer.parentElement, depth = 0;
       root && root !== document.body && depth < 8;
       root = root.parentElement, depth += 1) {
    const controls = root.querySelectorAll(
      'button,[role="button"],input[type="submit"]'
    );
    for (const control of controls) {
      const rect = control.getBoundingClientRect();
      if (rect.width < 16 || rect.height < 16) continue;
      if (control.disabled || control.getAttribute("aria-disabled") === "true") {
        continue;
      }
      const label = norm(
        `${control.getAttribute("aria-label") || ""} ` +
        `${control.getAttribute("title") || ""} ` +
        `${control.getAttribute("value") || ""} ${control.innerText || ""}`
      );
      const typedSubmit = control.matches(
        'button[type="submit"],input[type="submit"]'
      );
      if (
        !typedSubmit
        && !wanted.some(term => label === term || label.includes(term))
      ) {
        continue;
      }
      control.setAttribute("data-fbspy-action-control", marker);
      return {
        status: "located",
        action: "comment_submit",
        label,
        depth,
        strategy: typedSubmit ? "submit_type" : "accessible_label",
      };
    }
  }
  return {status: "submit_control_not_found", action: "comment_submit"};
}
"""


def _click_scoped_control(
    page: Page,
    *,
    element_id: str,
    action: str,
    positive: list[str],
    negative: list[str],
    exclude: list[str],
    timeout_ms: int = 8000,
) -> dict[str, Any]:
    marker = uuid4().hex
    result = page.evaluate(
        _CLICK_CONTROL_JS,
        {
            "elementId": element_id,
            "action": action,
            "positive": positive,
            "negative": negative,
            "exclude": exclude,
            "marker": marker,
        },
    )
    if result.get("status") != "located":
        return result
    _trusted_click(page, marker, timeout_ms=timeout_ms)
    result["status"] = "clicked"
    return result


def _trusted_click(page: Page, marker: str, *, timeout_ms: int) -> None:
    control = page.locator(f'[data-fbspy-action-control="{marker}"]')
    clicked = control.evaluate(
        "element => { element.click(); return true; }",
        timeout=timeout_ms,
    )
    if not clicked:
        raise RuntimeError("action control click was not dispatched")
    page.wait_for_timeout(250)


def _wait_for_active_state(
    page: Page,
    script: str,
    payload: dict[str, Any],
    *,
    timeout_ms: int,
) -> dict[str, Any]:
    deadline = time.monotonic() + max(0, timeout_ms) / 1000
    result: dict[str, Any] = {"status": "inactive"}
    while True:
        result = page.evaluate(script, payload)
        if (
            result.get("status") in {"active", "root_not_found"}
            or time.monotonic() >= deadline
        ):
            return result
        page.wait_for_timeout(400)


def _text(value: Any) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip().casefold()


def _domain(value: Any) -> str:
    cleaned = _text(value)
    cleaned = re.sub(r"^https?://", "", cleaned).split("/", 1)[0]
    return cleaned.removeprefix("www.")


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


def _similarity(left: Any, right: Any) -> float:
    a = _text(left)
    b = _text(right)
    if not a or not b:
        return 0.0
    if a == b:
        return 1.0
    return SequenceMatcher(None, a, b).ratio()


_CLICK_CONTROL_JS = r"""
({elementId, action, positive, negative, exclude, marker}) => {
  const root = document.querySelector(`[data-fbspy-id="${elementId}"]`);
  if (!root) return {status: "root_not_found", action};
  root.scrollIntoView({block: "center", inline: "nearest"});
  const norm = value => (value || "").toLocaleLowerCase().replace(/\s+/g, " ").trim();
  const controls = [...root.querySelectorAll('button,[role="button"]')];
  for (const el of controls) {
    const label = norm(`${el.getAttribute("aria-label") || ""} ${el.innerText || ""}`);
    if (!label || exclude.some(term => label.includes(norm(term)))) continue;
    if (!positive.some(term => label.includes(norm(term)))) continue;
    const pressed = el.getAttribute("aria-pressed") === "true";
    if (pressed || negative.some(term => label.includes(norm(term)))) {
      return {status: "already_active", action, label, pressed};
    }
    el.setAttribute("data-fbspy-action-control", marker);
    return {status: "located", action, label};
  }
  return {status: "control_not_found", action};
}
"""


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


_READ_SCOPED_CONTROL_STATE_JS = r"""
({elementId, active}) => {
  const root = document.querySelector(`[data-fbspy-id="${elementId}"]`);
  if (!root) return {status: "root_not_found"};
  const norm = value => (value || "").toLocaleLowerCase().replace(/\s+/g, " ").trim();
  const controls = [...root.querySelectorAll('button,[role="button"]')];
  for (const el of controls) {
    const label = norm(`${el.getAttribute("aria-label") || ""} ${el.innerText || ""}`);
    if (el.getAttribute("aria-pressed") === "true") {
      return {status: "active", label, pressed: true};
    }
    if (active.some(term => label.includes(norm(term)))) {
      return {status: "active", label, pressed: false};
    }
  }
  return {status: "inactive"};
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
    root = rootFor(el, false);
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

    // Some mobile deep links fall back to the feed and Facebook replaces the
    // landing metadata with placeholders. In that case use the advertiser only
    // when it identifies exactly one post card on the freshly opened page.
    if (!root && expectedAdvertiser) {
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

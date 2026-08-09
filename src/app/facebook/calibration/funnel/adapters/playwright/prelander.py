from __future__ import annotations

import random
import time
from typing import Any, cast

from playwright.sync_api import Error as PlaywrightError
from playwright.sync_api import Page

from ...models import OfferFunnelPolicy
from ...security import domain, redact_error, redact_url
from .controls import best_text_control, control_text, wait_for_dom
from .forms import find_offer_form
from .quiz import complete_quiz
from .terms import CTA_EXCLUDES, CTA_TERMS


def browse_offer_page(page: Page, policy: OfferFunnelPolicy) -> dict[str, Any]:
    steps: list[dict[str, Any]] = []
    opened_pages: list[Page] = []
    offer_signal = False
    wait_for_dom(page, policy.navigation_timeout_ms)

    quiz = complete_quiz(page, max_questions=policy.quiz_max_questions)
    if quiz.get("status") != "not_found":
        steps.append(quiz)
        offer_signal = True

    form = find_offer_form(page)
    if form is None:
        scroll = scroll_prelander(
            page,
            seconds=policy.browse_seconds,
            max_scrolls=policy.max_scrolls,
        )
        steps.append(scroll)
        form = find_offer_form(page)

    if form is None:
        cta = click_prelander_cta(page, timeout_ms=policy.navigation_timeout_ms)
        opened_page = cta.pop("_page", None)
        if opened_page is not None:
            page = cast(Page, opened_page)
            opened_pages.append(page)
        steps.append(cta)
        if cta.get("status") in {"clicked", "clicked_new_page"}:
            wait_for_dom(page, policy.navigation_timeout_ms)
            quiz = complete_quiz(page, max_questions=policy.quiz_max_questions)
            if quiz.get("status") != "not_found":
                steps.append(quiz)
                offer_signal = True
            form = find_offer_form(page)
            offer_signal = offer_signal or form is not None

    offer_signal = (
        offer_signal
        or form is not None
        or any(
            step.get("action") == "prelander_cta"
            and step.get("status") in {"clicked", "clicked_new_page"}
            for step in steps
        )
    )

    return {
        "status": "offer_engaged" if offer_signal else "landing_viewed",
        "form_detected": form is not None,
        "success_confirmed": False,
        "final_url": redact_url(page.url),
        "final_domain": domain(page.url),
        "steps": steps,
        "_active_page": page,
        "_opened_pages": opened_pages,
    }


def scroll_prelander(
    page: Page,
    *,
    seconds: float,
    max_scrolls: int,
) -> dict[str, Any]:
    started = time.monotonic()
    scrolls = 0
    deadline = started + max(0.0, seconds)
    while scrolls < max(0, max_scrolls) and time.monotonic() < deadline:
        try:
            state = cast(
                dict[str, Any],
                page.evaluate(
                    """() => ({
                        y: window.scrollY,
                        viewport: window.innerHeight,
                        height: Math.max(document.body.scrollHeight, document.documentElement.scrollHeight),
                    })"""
                ),
            )
            if state["y"] + state["viewport"] >= state["height"] - 24:
                break
            distance = max(
                260,
                round(float(state["viewport"]) * random.uniform(0.55, 0.85)),
            )
            page.evaluate(
                "dy => window.scrollBy({top: dy, behavior: 'smooth'})",
                distance,
            )
            scrolls += 1
            page.wait_for_timeout(random.randint(600, 1200))
        except PlaywrightError:
            break
    return {
        "action": "prelander_scroll",
        "status": "completed" if scrolls else "not_needed",
        "scrolls": scrolls,
        "duration_seconds": round(time.monotonic() - started, 3),
    }


def click_prelander_cta(page: Page, *, timeout_ms: int) -> dict[str, Any]:
    before_url = page.url
    before_pages = set(page.context.pages)
    locator = best_text_control(page, CTA_TERMS, excludes=CTA_EXCLUDES)
    if locator is None:
        return {"action": "prelander_cta", "status": "not_found"}
    try:
        label = control_text(locator)
        locator.scroll_into_view_if_needed(timeout=3000)
        locator.click(timeout=min(max(1, timeout_ms), 8000), no_wait_after=True)
        deadline = time.monotonic() + max(0, timeout_ms) / 1000
        while time.monotonic() < deadline:
            new_pages = [
                candidate
                for candidate in page.context.pages
                if candidate not in before_pages
            ]
            if new_pages:
                candidate = new_pages[-1]
                try:
                    candidate.wait_for_load_state("domcontentloaded", timeout=3000)
                except PlaywrightError:
                    pass
                return {
                    "action": "prelander_cta",
                    "status": "clicked_new_page",
                    "label": label,
                    "url": redact_url(candidate.url),
                    "_page": candidate,
                }
            if page.url != before_url or find_offer_form(page) is not None:
                return {
                    "action": "prelander_cta",
                    "status": "clicked",
                    "label": label,
                    "url": redact_url(page.url),
                }
            page.wait_for_timeout(250)
        return {
            "action": "prelander_cta",
            "status": "clicked_unconfirmed",
            "label": label,
        }
    except PlaywrightError as exc:
        return {
            "action": "prelander_cta",
            "status": "click_failed",
            "error": redact_error(exc),
        }

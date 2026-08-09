from __future__ import annotations

import random
from typing import Any

from playwright.sync_api import Error as PlaywrightError
from playwright.sync_api import Page

from ...security import fold


def best_text_control(
    scope: Any,
    terms: tuple[str, ...],
    *,
    excludes: tuple[str, ...],
) -> Any | None:
    best = None
    best_score = -1
    try:
        controls = scope.locator("a,button,[role='button']").all()
    except PlaywrightError:
        return None
    for control in controls:
        try:
            if not control.is_visible():
                continue
            text = fold(control_text(control))
            if not text or len(text) > 100 or any(term in text for term in excludes):
                continue
            score = max((len(term) for term in terms if term in text), default=-1)
            if score > best_score:
                best, best_score = control, score
        except PlaywrightError:
            continue
    return best


def click_text_control(
    scope: Any,
    terms: tuple[str, ...],
    *,
    excludes: tuple[str, ...],
) -> bool:
    control = best_text_control(scope, terms, excludes=excludes)
    if control is None:
        return False
    try:
        control.scroll_into_view_if_needed(timeout=2000)
        control.click(timeout=3000)
        scope.wait_for_timeout(random.randint(400, 800))
        return True
    except PlaywrightError:
        return False


def click_first_selector(scope: Any, selectors: tuple[str, ...]) -> bool:
    control = first_visible_from_selectors(scope, selectors)
    if control is None:
        return False
    try:
        control.scroll_into_view_if_needed(timeout=2000)
        control.click(timeout=3000)
        scope.wait_for_timeout(random.randint(400, 800))
        return True
    except PlaywrightError:
        return False


def first_visible_from_selectors(
    scope: Any,
    selectors: tuple[str, ...],
) -> Any | None:
    for selector in selectors:
        try:
            for locator in scope.locator(selector).all():
                if locator.is_visible():
                    return locator
        except PlaywrightError:
            continue
    return None


def control_text(control: Any) -> str:
    return str(
        control.evaluate(
            "el => el.innerText || el.value || el.getAttribute('aria-label') || ''"
        )
        or ""
    ).strip()


def wait_for_dom(page: Page, timeout_ms: int) -> None:
    try:
        page.wait_for_load_state("domcontentloaded", timeout=max(1, timeout_ms))
    except PlaywrightError:
        pass

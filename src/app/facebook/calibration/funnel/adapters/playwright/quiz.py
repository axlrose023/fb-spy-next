from __future__ import annotations

import random
from typing import Any

from playwright.sync_api import Error as PlaywrightError
from playwright.sync_api import Page

from ...security import fold
from .controls import (
    click_first_selector,
    click_text_control,
    control_text,
    first_visible_from_selectors,
)
from .forms import find_offer_form
from .success import detect_success
from .terms import CTA_EXCLUDES

QUIZ_START_TERMS = (
    "start",
    "begin",
    "take quiz",
    "comenzar",
    "empezar",
    "iniciar",
    "continuar",
    "siguiente",
)
QUIZ_ANSWER_SELECTORS = (
    ".answer-btn",
    ".q-answer",
    "[class*='answer-option']",
    "[class*='answer-variant']",
    "[class*='quiz-answer']",
    "[class*='quiz-option']",
    "[class*='question-option']",
    "[class*='survey-option']",
    "[data-answer]",
    "[data-option]",
    "[data-choice]",
    "[role='option']",
    "[role='radio']",
    "[class*='quiz'] label:has(input[type='radio'])",
    "[class*='question'] label:has(input[type='radio'])",
)
QUIZ_START_SELECTORS = (
    "button.start-page__button",
    "button.next-btn",
    ".start-page__button",
    ".quiz-start-btn",
    ".start-quiz",
    "[class*='start-btn']",
    "[class*='quiz-start']",
    "[class*='begin-btn']",
)
QUIZ_NEXT_TERMS = (
    "next",
    "continue",
    "siguiente",
    "continuar",
    "dalej",
    "devam",
)


def complete_quiz(page: Page, *, max_questions: int) -> dict[str, Any]:
    if find_offer_form(page) is not None:
        return {"action": "quiz", "status": "not_found", "answered": 0}
    started = click_first_selector(page, QUIZ_START_SELECTORS) or click_text_control(
        page,
        QUIZ_START_TERMS,
        excludes=CTA_EXCLUDES,
    )
    answered = 0
    unchanged_answers = 0
    while answered < max(0, max_questions):
        if find_offer_form(page) is not None or (
            (started or answered > 0) and detect_success(page)
        ):
            return {
                "action": "quiz",
                "status": "completed",
                "started": started,
                "answered": answered,
            }
        before_state = quiz_state(page)
        answer = first_visible_from_selectors(page, QUIZ_ANSWER_SELECTORS)
        if answer is None:
            break
        try:
            answer.scroll_into_view_if_needed(timeout=2000)
            answer.click(timeout=3000)
            answered += 1
            page.wait_for_timeout(random.randint(500, 1000))
            if find_offer_form(page) is None and not detect_success(page):
                click_text_control(
                    page,
                    QUIZ_NEXT_TERMS,
                    excludes=CTA_EXCLUDES,
                )
            after_state = quiz_state(page)
            if after_state and after_state == before_state:
                unchanged_answers += 1
                if unchanged_answers >= 2:
                    break
            else:
                unchanged_answers = 0
        except PlaywrightError:
            break
    status = "progressed" if answered else "not_found"
    return {
        "action": "quiz",
        "status": status,
        "started": started,
        "answered": answered,
    }


def quiz_state(page: Page) -> tuple[str, ...]:
    values: list[str] = []
    for selector in QUIZ_ANSWER_SELECTORS:
        try:
            for locator in page.locator(selector).all():
                if locator.is_visible():
                    values.append(fold(control_text(locator))[:120])
        except PlaywrightError:
            continue
    return tuple(value for value in values if value)

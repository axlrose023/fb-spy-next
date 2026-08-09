from __future__ import annotations

from typing import Any
from urllib.parse import urlsplit

from playwright.sync_api import Error as PlaywrightError
from playwright.sync_api import Page

from ...security import fold

SUCCESS_PHRASES = (
    "thank you",
    "thanks for registering",
    "registration received",
    "registration successful",
    "registro recibido",
    "registro completado",
    "gracias por registrarte",
    "solicitud recibida",
    "obrigado",
    "cadastro realizado",
    "kayit basarili",
    "basvurunuz alindi",
)
SUCCESS_URL_PARTS = (
    "thank-you",
    "thank_you",
    "thankyou",
    "thanks",
    "success",
    "complete",
    "completed",
    "confirmation",
    "registered",
)


def detect_success(page: Page) -> bool:
    scopes: list[Any] = [
        page,
        *[frame for frame in page.frames if frame != page.main_frame],
    ]
    for scope in scopes:
        try:
            parsed = urlsplit(scope.url)
            folded_path = fold(parsed.path)
            if any(part in folded_path for part in SUCCESS_URL_PARTS):
                return True
            body = fold(scope.locator("body").inner_text(timeout=2000)[:12_000])
            if any(phrase in body for phrase in SUCCESS_PHRASES):
                return True
        except PlaywrightError:
            continue
    return False


def find_success_page(page: Page, before_pages: set[Page]) -> Page | None:
    if detect_success(page):
        return page
    for candidate in page.context.pages:
        if candidate in before_pages or candidate.is_closed():
            continue
        try:
            candidate.wait_for_load_state("domcontentloaded", timeout=1000)
        except PlaywrightError:
            pass
        if detect_success(candidate):
            return candidate
    return None

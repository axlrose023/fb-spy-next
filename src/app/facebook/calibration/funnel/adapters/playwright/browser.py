from __future__ import annotations

from typing import Any

from playwright.sync_api import Error as PlaywrightError
from playwright.sync_api import Page

from ...security import redact_error, redact_url
from .controls import best_text_control, first_visible_from_selectors
from .forms import find_offer_form
from .quiz import QUIZ_START_SELECTORS
from .terms import CTA_EXCLUDES, CTA_TERMS


def public_action(action: dict[str, Any]) -> dict[str, Any]:
    public: dict[str, Any] = {}
    for key, value in action.items():
        if isinstance(value, str) and (key == "href" or key.endswith("_url")):
            public[key] = redact_url(value)
        elif isinstance(value, str) and "error" in key:
            public[key] = redact_error(value)
        else:
            public[key] = value
    return public


def goto_direct_offer(page: Page, url: str, *, timeout_ms: int) -> Any:
    try:
        return page.goto(
            url,
            wait_until="domcontentloaded",
            timeout=timeout_ms,
        )
    except PlaywrightError as exc:
        if "ERR_CERT_AUTHORITY_INVALID" not in str(exc):
            raise
        session = page.context.new_cdp_session(page)
        session.send(
            "Security.setIgnoreCertificateErrors",
            {"ignore": True},
        )
        return page.goto(
            url,
            wait_until="domcontentloaded",
            timeout=timeout_ms,
        )


def has_offer_signal(page: Page) -> bool:
    if find_offer_form(page) is not None:
        return True
    if first_visible_from_selectors(page, QUIZ_START_SELECTORS) is not None:
        return True
    return best_text_control(page, CTA_TERMS, excludes=CTA_EXCLUDES) is not None


def close_pages(pages: list[Page]) -> None:
    for page in pages:
        try:
            if not page.is_closed():
                page.close(run_before_unload=False)
        except PlaywrightError:
            pass

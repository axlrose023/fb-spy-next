from __future__ import annotations

from collections.abc import Callable

from playwright.sync_api import Error as PlaywrightError
from playwright.sync_api import Page, Response

from app.facebook.navigation import (
    PROXY_CERTIFICATE_AUTHORITY_ERROR as PROXY_CERTIFICATE_AUTHORITY_ERROR,
)
from app.facebook.navigation import (
    TRANSIENT_NAVIGATION_ERRORS as TRANSIENT_NAVIGATION_ERRORS,
)
from app.facebook.navigation import (
    is_transient_navigation_error as is_transient_navigation_error,
)

BROWSER_CONTEXT_CLOSED_ERRORS = (
    "Target page, context or browser has been closed",
    "BrowserContext.new_page: Target page, context or browser has been closed",
)


class SavedPostAccessError(RuntimeError):
    """The profile or its proxy blocked direct access to a saved post."""


def open_saved_post(
    page: Page,
    url: str,
    *,
    timeout_ms: int,
    ignore_certificate_errors: Callable[[Page], bool],
) -> Response | None:
    response = goto_saved_post(
        page,
        url,
        timeout_ms=timeout_ms,
        ignore_certificate_errors=ignore_certificate_errors,
    )
    if response and response.status in {401, 403}:
        try:
            page_title = page.title().strip()
        except PlaywrightError:
            page_title = ""
        detail = f" ({page_title})" if page_title else ""
        raise SavedPostAccessError(
            f"saved Facebook post access blocked: HTTP {response.status}{detail}"
        )
    if response and response.status >= 400:
        raise RuntimeError(f"saved Facebook post returned HTTP {response.status}")
    return response


def goto_saved_post(
    page: Page,
    url: str,
    *,
    timeout_ms: int,
    attempts: int = 3,
    ignore_certificate_errors: Callable[[Page], bool],
) -> Response | None:
    ignored_proxy_certificate_error = False
    for attempt in range(1, max(1, attempts) + 1):
        try:
            return page.goto(
                url,
                wait_until="domcontentloaded",
                timeout=timeout_ms,
            )
        except PlaywrightError as exc:
            if (
                not ignored_proxy_certificate_error
                and PROXY_CERTIFICATE_AUTHORITY_ERROR in str(exc)
                and ignore_certificate_errors(page)
            ):
                ignored_proxy_certificate_error = True
                continue
            transient = is_transient_navigation_error(exc)
            if not transient or attempt >= attempts:
                raise
            page.wait_for_timeout(1500 * attempt)
    raise RuntimeError("saved Facebook post navigation exhausted retries")


def is_browser_context_closed_error(exc: Exception) -> bool:
    return any(message in str(exc) for message in BROWSER_CONTEXT_CLOSED_ERRORS)

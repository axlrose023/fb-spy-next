from __future__ import annotations

import random
import time
from typing import Any

from playwright.sync_api import Error as PlaywrightError
from playwright.sync_api import Page

from ...models import OfferFunnelPolicy, OfferIdentity
from ...security import domain_allowed, fold, redact_error, redact_url
from .fields import (
    field_metadata,
    form_fields,
    select_phone_country,
    submit_button,
)
from .success import find_success_page

FORM_SELECTORS = (
    "form",
    "#form_block",
    ".form-container",
    "[class*='form-block']",
    "[class*='contact-form']",
    "[class*='lead-form']",
)
DANGEROUS_FIELD_TERMS = (
    "card number",
    "credit card",
    "debit card",
    "cvv",
    "cvc",
    "iban",
    "swift",
    "bank account",
    "passport",
    "identity document",
    "social security",
    "tax id",
)


def handle_offer_form(
    page: Page,
    *,
    policy: OfferFunnelPolicy,
    identity: OfferIdentity,
    already_submitted: bool = False,
) -> dict[str, Any]:
    found = find_offer_form(page)
    if found is None:
        return {"action": "offer_form", "status": "not_found"}
    _scope, form = found
    inspection = inspect_offer_form(form)
    result: dict[str, Any] = {
        "action": "offer_form",
        "status": "detected",
        "field_kinds": sorted(inspection["fields"]),
        "dangerous_fields": inspection["dangerous_fields"],
        "fields_filled": [],
        "submitted": False,
        "success_confirmed": False,
    }
    if inspection["dangerous_fields"]:
        result["status"] = "blocked_dangerous_fields"
        return result
    if policy.submit_mode == "disabled":
        return result
    if not identity.complete:
        result["status"] = "identity_missing"
        return result

    select_phone_country(form, identity.country_code)
    filled = fill_offer_form(form, inspection["fields"], identity)
    result["fields_filled"] = filled
    if policy.submit_mode == "fill_only":
        result["status"] = "filled_not_submitted"
        return result
    if policy.submit_mode != "allowlisted":
        result["status"] = "invalid_submit_mode"
        return result
    if already_submitted:
        result["status"] = "repeat_submit_blocked"
        return result
    if not domain_allowed(page.url, policy.submit_allow_domains):
        result["status"] = "submit_domain_not_allowed"
        return result
    if not {"email", "phone"}.intersection(filled):
        result["status"] = "required_contact_fields_not_filled"
        return result

    button = submit_button(form)
    if button is None:
        result["status"] = "submit_control_not_found"
        return result
    before_url = page.url
    before_pages = set(page.context.pages)
    try:
        button.scroll_into_view_if_needed(timeout=3000)
        button.click(timeout=5000, no_wait_after=True)
        result["submitted"] = True
    except PlaywrightError as exc:
        result["status"] = "submit_failed"
        result["error"] = redact_error(exc)
        return result

    deadline = time.monotonic() + max(0.0, policy.success_wait_seconds)
    while time.monotonic() < deadline:
        success_page = find_success_page(page, before_pages)
        if success_page is not None:
            result["status"] = "success_confirmed"
            result["success_confirmed"] = True
            result["success_url"] = redact_url(success_page.url)
            if success_page is not page:
                result["_opened_pages"] = [success_page]
                result["_active_page"] = success_page
            return result
        if page.url != before_url and find_offer_form(page) is None:
            result["status"] = "submitted_navigation_unconfirmed"
        page.wait_for_timeout(500)
    result["status"] = "submitted_unconfirmed"
    return result


def find_offer_form(page: Page) -> tuple[Any, Any] | None:
    scopes: list[Any] = [
        page,
        *[frame for frame in page.frames if frame != page.main_frame],
    ]
    for scope in scopes:
        for selector in FORM_SELECTORS:
            try:
                for form in scope.locator(selector).all():
                    if not form.is_visible():
                        continue
                    inputs = form.locator(
                        "input:not([type='hidden']), select, textarea"
                    )
                    if inputs.count() <= 0:
                        continue
                    fields = form_fields(form)
                    if {"email", "phone"}.intersection(fields):
                        return scope, form
            except PlaywrightError:
                continue
    return None


def inspect_offer_form(form: Any) -> dict[str, Any]:
    fields = form_fields(form)
    dangerous: list[str] = []
    try:
        for element in form.locator("input,select,textarea").all():
            metadata = field_metadata(element)
            haystack = fold(" ".join(str(value or "") for value in metadata.values()))
            field_type = str(metadata.get("type") or "").casefold()
            if field_type in {"password", "file"}:
                dangerous.append(field_type)
            dangerous.extend(term for term in DANGEROUS_FIELD_TERMS if term in haystack)
    except PlaywrightError:
        pass
    return {"fields": fields, "dangerous_fields": sorted(set(dangerous))}


def fill_offer_form(
    form: Any,
    fields: dict[str, Any],
    identity: OfferIdentity,
) -> list[str]:
    values = {
        "first_name": identity.first_name,
        "last_name": identity.last_name,
        "full_name": identity.full_name,
        "email": identity.email,
        "phone": identity.phone,
    }
    filled: list[str] = []
    for kind in ("first_name", "last_name", "full_name", "email", "phone"):
        element = fields.get(kind)
        value = values[kind]
        if element is None or not value:
            continue
        try:
            element.scroll_into_view_if_needed(timeout=2000)
            element.fill(value, timeout=3000)
            filled.append(kind)
            time.sleep(random.uniform(0.15, 0.35))
        except PlaywrightError:
            continue
    try:
        for checkbox in form.locator("input[type='checkbox'][required]").all():
            if checkbox.is_visible() and not checkbox.is_checked():
                checkbox.check(timeout=2000)
    except PlaywrightError:
        pass
    return filled

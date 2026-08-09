from __future__ import annotations

from typing import Any, cast

from playwright.sync_api import Error as PlaywrightError

from ...security import fold
from .controls import first_visible_from_selectors

PHONE_DROPDOWN_SELECTORS = (
    ".iti__selected-flag",
    ".iti__selected-country",
    ".iti-aio__selected-country",
)
PHONE_COUNTRY_SELECTORS = (
    ".iti__country",
    ".iti-aio__country",
)
SUBMIT_SELECTORS = (
    "button[type='submit']",
    "input[type='submit']",
    "button:not([type])",
    "[class*='submit']",
    "[id*='submit']",
)


def form_fields(form: Any) -> dict[str, Any]:
    fields: dict[str, Any] = {}
    try:
        elements = form.locator("input:not([type='hidden']), textarea").all()
    except PlaywrightError:
        return fields
    for element in elements:
        try:
            if (
                not element.is_visible()
                or element.is_disabled()
                or element.is_editable() is False
            ):
                continue
            metadata = field_metadata(element)
            kind = field_kind(metadata)
            if kind and kind not in fields:
                fields[kind] = element
        except PlaywrightError:
            continue
    if "full_name" in fields and "first_name" in fields:
        fields.pop("full_name", None)
    return fields


def field_metadata(element: Any) -> dict[str, str]:
    return cast(
        dict[str, str],
        element.evaluate(
            """el => {
                const labels = el.labels ? [...el.labels].map(label => label.innerText || '').join(' ') : '';
                return {
                    type: el.getAttribute('type') || '',
                    name: el.getAttribute('name') || '',
                    id: el.id || '',
                    placeholder: el.getAttribute('placeholder') || '',
                    autocomplete: el.getAttribute('autocomplete') || '',
                    aria: el.getAttribute('aria-label') || '',
                    labels,
                };
            }"""
        ),
    )


def field_kind(metadata: dict[str, str]) -> str:
    field_type = str(metadata.get("type") or "").casefold()
    autocomplete = str(metadata.get("autocomplete") or "").casefold()
    haystack = fold(" ".join(str(value or "") for value in metadata.values()))
    if (
        field_type == "email"
        or "email" in autocomplete
        or any(term in haystack for term in ("email", "e-mail", "correo", "mail"))
    ):
        return "email"
    if (
        field_type == "tel"
        or "tel" in autocomplete
        or any(
            term in haystack
            for term in ("phone", "telephone", "telefono", "mobile", "whatsapp")
        )
    ):
        return "phone"
    if "given-name" in autocomplete or any(
        term in haystack
        for term in ("first_name", "firstname", "first name", "fname", "nombre de pila")
    ):
        return "first_name"
    if "family-name" in autocomplete or any(
        term in haystack
        for term in (
            "last_name",
            "lastname",
            "last name",
            "lname",
            "surname",
            "apellido",
        )
    ):
        return "last_name"
    if autocomplete == "name" or any(
        term in haystack for term in ("full_name", "fullname", "full name", "your name")
    ):
        return "full_name"
    name = fold(str(metadata.get("name") or ""))
    placeholder = fold(str(metadata.get("placeholder") or ""))
    if name in {"name", "nombre"} or placeholder in {"name", "nombre", "nome"}:
        return "first_name"
    return ""


def submit_button(form: Any) -> Any | None:
    return first_visible_from_selectors(form, SUBMIT_SELECTORS)


def select_phone_country(form: Any, country_code: str) -> bool:
    wanted = country_code.strip().casefold()
    if not wanted:
        return False
    try:
        root = form.locator("xpath=ancestor-or-self::*[contains(@class, 'iti')][1]")
        scope = root.first if root.count() else form
        dropdown = first_visible_from_selectors(scope, PHONE_DROPDOWN_SELECTORS)
        if dropdown is None:
            dropdown = first_visible_from_selectors(
                form.page,
                PHONE_DROPDOWN_SELECTORS,
            )
        if dropdown is None:
            return False
        dropdown.click(timeout=3000)
        page = form.page
        for selector in PHONE_COUNTRY_SELECTORS:
            candidate = page.locator(f"{selector}[data-country-code='{wanted}']").first
            if candidate.count() and candidate.is_visible():
                candidate.click(timeout=3000)
                return True
    except PlaywrightError:
        return False
    return False

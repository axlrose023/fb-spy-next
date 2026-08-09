from __future__ import annotations

import json
import random
import re
import time
import unicodedata
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlsplit, urlunsplit

from playwright.sync_api import Error as PlaywrightError
from playwright.sync_api import Page

from app.facebook.calibration import open_ad_landing
from app.services.facebook.calibration import CalibrationTarget

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
CTA_TERMS = (
    "register",
    "sign up",
    "get started",
    "start now",
    "learn more",
    "more information",
    "continue",
    "apply now",
    "join now",
    "claim now",
    "begin",
    "registr",
    "comenzar",
    "empezar",
    "continuar",
    "siguiente",
    "mas informacion",
    "participar",
    "saiba mais",
    "cadastro",
    "inscreva",
    "devam",
    "basla",
)
CTA_EXCLUDES = (
    "deposit",
    "pay now",
    "checkout",
    "buy now",
    "download",
    "log in",
    "login",
    "shipping",
    "delivery",
    "privacy",
    "cookie",
    "terms and conditions",
    "customer service",
    "next page",
    "pagina siguiente",
    "page suivante",
)
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
PIXEL_HOST_SUFFIXES = (
    "facebook.com",
    "facebook.net",
)
URL_IN_TEXT = re.compile(r"https?://[^\s\"'<>]+", re.IGNORECASE)
PHONE_DROPDOWN_SELECTORS = (
    ".iti__selected-flag",
    ".iti__selected-country",
    ".iti-aio__selected-country",
)
PHONE_COUNTRY_SELECTORS = (
    ".iti__country",
    ".iti-aio__country",
)


@dataclass(frozen=True, slots=True)
class OfferIdentity:
    first_name: str = ""
    last_name: str = ""
    email: str = ""
    phone: str = ""
    country_code: str = ""

    @property
    def full_name(self) -> str:
        return " ".join(part for part in (self.first_name, self.last_name) if part)

    @property
    def complete(self) -> bool:
        phone_digits = "".join(char for char in self.phone if char.isdigit())
        return bool(
            self.first_name
            and "@" in self.email
            and len(phone_digits) >= 7
        )


@dataclass(frozen=True, slots=True)
class OfferFunnelPolicy:
    enabled: bool = True
    direct_offer_fallback: bool = True
    browse_seconds: float = 45.0
    max_scrolls: int = 12
    quiz_max_questions: int = 10
    submit_mode: str = "disabled"
    submit_allow_domains: tuple[str, ...] = ()
    success_wait_seconds: float = 20.0
    max_retained_tabs: int = 6
    navigation_timeout_ms: int = 20_000


@dataclass(slots=True)
class _OpenedLanding:
    page: Page
    opened_pages: list[Page]
    result: dict[str, Any]


def load_offer_identity(
    path: Path | None,
    *,
    profile_uuid: str = "",
    country: str | None = None,
) -> OfferIdentity:
    if path is None:
        return OfferIdentity()
    payload = json.loads(path.expanduser().read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("Offer identity JSON must contain an object")
    payload = _select_identity_payload(
        payload,
        profile_uuid=profile_uuid,
        country=country,
    )
    return OfferIdentity(
        first_name=str(payload.get("first_name") or "").strip(),
        last_name=str(payload.get("last_name") or "").strip(),
        email=str(payload.get("email") or "").strip(),
        phone=str(payload.get("phone") or "").strip(),
        country_code=str(payload.get("country_code") or "").strip().upper(),
    )


class OfferFunnelSession:
    """Drive relevant offer funnels in one persistent Octo browser context."""

    def __init__(
        self,
        context,
        *,
        policy: OfferFunnelPolicy,
        identity: OfferIdentity | None = None,
    ) -> None:
        self.context = context
        self.policy = policy
        self.identity = identity or OfferIdentity()
        self.retained_pages: list[Page] = []
        self.submitted_targets: set[str] = set()
        self.pixel_events: list[str] = []
        self._request_handler = self._observe_request
        try:
            context.on("request", self._request_handler)
        except Exception:
            pass

    def run(
        self,
        target: CalibrationTarget,
        *,
        source_page: Page | None = None,
        element_id: str = "",
    ) -> dict[str, Any]:
        started = time.monotonic()
        result: dict[str, Any] = {
            "action": "offer_funnel",
            "status": "not_started",
            "opening": "none",
            "target": public_offer_target(target),
            "steps": [],
        }
        if not self.policy.enabled:
            return {**result, "status": "disabled"}

        opened = self._open_landing(target, source_page, element_id)
        result["steps"].append(opened.result)
        result["opening"] = str(opened.result.get("opening") or "none")
        if opened.result.get("status") != "visited":
            result["status"] = str(opened.result.get("status") or "open_failed")
            result["duration_seconds"] = round(time.monotonic() - started, 3)
            return result

        page = opened.page
        if opened.result.get("cross_domain_redirect") and not _has_offer_signal(page):
            result["status"] = "redirected_without_offer_signals"
            result["duration_seconds"] = round(time.monotonic() - started, 3)
            _close_pages(opened.opened_pages)
            return result
        browse = browse_offer_page(page, self.policy)
        page = browse.pop("_active_page", page)
        opened.opened_pages.extend(browse.pop("_opened_pages", []))
        result["steps"].extend(browse.pop("steps", []))
        result.update(browse)

        submit_key = _target_key(target, page.url)
        if result.get("form_detected"):
            form_result = handle_offer_form(
                page,
                policy=self.policy,
                identity=self.identity,
                already_submitted=submit_key in self.submitted_targets,
            )
            page = form_result.pop("_active_page", page)
            opened.opened_pages.extend(form_result.pop("_opened_pages", []))
            result["steps"].append(form_result)
            result.update({
                "form_status": form_result.get("status"),
                "fields_filled": form_result.get("fields_filled", []),
                "form_submitted": form_result.get("submitted", False),
                "success_confirmed": form_result.get("success_confirmed", False),
            })
            if form_result.get("submitted"):
                self.submitted_targets.add(submit_key)

        result["status"] = _funnel_status(result)
        result["pixel_events"] = sorted(set(self.pixel_events))
        result["duration_seconds"] = round(time.monotonic() - started, 3)
        if result["status"] == "landing_viewed":
            _close_pages(opened.opened_pages)
        else:
            self._retain(page, opened.opened_pages)
        return result

    def summary(self) -> dict[str, Any]:
        return {
            "retained_tabs": len([page for page in self.retained_pages if not page.is_closed()]),
            "submitted_targets": len(self.submitted_targets),
            "pixel_events": sorted(set(self.pixel_events)),
            "submit_mode": self.policy.submit_mode,
        }

    def close(self) -> None:
        try:
            self.context.remove_listener("request", self._request_handler)
        except Exception:
            pass
        for page in list(self.retained_pages):
            try:
                if not page.is_closed():
                    page.close(run_before_unload=False)
            except PlaywrightError:
                pass
        self.retained_pages.clear()

    def _open_landing(
        self,
        target: CalibrationTarget,
        source_page: Page | None,
        element_id: str,
    ) -> _OpenedLanding:
        if source_page is not None and element_id:
            click_result, landing_page, opened_pages = open_ad_landing(
                source_page,
                element_id,
                cta=target.cta,
                expected_url=target.landing_full or target.landing_clean or "",
                timeout_ms=self.policy.navigation_timeout_ms,
            )
            click_result = _public_action(click_result)
            click_result["opening"] = "facebook_cta"
            if landing_page is not None and click_result.get("status") == "visited":
                mismatch = click_result.get("expected_domain_match") is False
                if not mismatch or _has_offer_signal(landing_page):
                    return _OpenedLanding(landing_page, opened_pages, click_result)
                click_result["status"] = "cta_domain_mismatch"
            _close_pages(opened_pages)
            if not self.policy.direct_offer_fallback:
                return _OpenedLanding(source_page, [], click_result)
            fallback_reason = str(click_result.get("status") or "facebook_cta_failed")
        else:
            click_result = None
            fallback_reason = "facebook_post_unavailable"

        if not self.policy.direct_offer_fallback:
            fallback = {
                "action": "landing_open",
                "status": "direct_fallback_disabled",
                "opening": "none",
            }
            return _OpenedLanding(source_page, [], fallback)  # type: ignore[arg-type]

        direct_url = offer_url(target)
        if not _external_http_url(direct_url):
            fallback = {
                "action": "landing_open",
                "status": "missing_direct_offer_url",
                "opening": "direct_offer",
            }
            return _OpenedLanding(source_page, [], fallback)  # type: ignore[arg-type]

        page = self.context.new_page()
        try:
            response = _goto_direct_offer(
                page,
                direct_url,
                timeout_ms=self.policy.navigation_timeout_ms,
            )
            status_code = response.status if response else None
            if status_code is not None and status_code >= 400:
                raise RuntimeError(f"direct offer returned HTTP {status_code}")
            source_domain = _domain(direct_url)
            final_domain = _domain(page.url)
            direct_result = {
                "action": "landing_open",
                "status": "visited",
                "opening": "direct_offer",
                "url": redact_url(page.url),
                "domain": final_domain,
                "source_domain": source_domain,
                "cross_domain_redirect": not _same_site(
                    source_domain,
                    final_domain,
                ),
                "http_status": status_code,
                "fallback_reason": fallback_reason,
            }
            if click_result is not None:
                direct_result["facebook_cta_attempt"] = click_result
            return _OpenedLanding(
                page,
                [page],
                direct_result,
            )
        except Exception as exc:
            _close_pages([page])
            return _OpenedLanding(
                page,
                [],
                {
                    "action": "landing_open",
                    "status": "direct_navigation_failed",
                    "opening": "direct_offer",
                    "url": redact_url(direct_url),
                    "error": redact_error(exc),
                },
            )

    def _retain(self, landing_page: Page, opened_pages: list[Page]) -> None:
        for page in [landing_page, *opened_pages]:
            if page not in self.retained_pages and not page.is_closed():
                self.retained_pages.append(page)
        limit = max(1, self.policy.max_retained_tabs)
        while len(self.retained_pages) > limit:
            oldest = self.retained_pages.pop(0)
            try:
                if not oldest.is_closed():
                    oldest.close(run_before_unload=False)
            except PlaywrightError:
                pass

    def _observe_request(self, request) -> None:
        try:
            parsed = urlsplit(request.url)
        except Exception:
            return
        host = (parsed.hostname or "").casefold()
        if not any(host == suffix or host.endswith(f".{suffix}") for suffix in PIXEL_HOST_SUFFIXES):
            return
        query = parse_qs(parsed.query)
        event = str((query.get("ev") or query.get("event") or [""])[0]).strip()
        if event and event not in self.pixel_events:
            self.pixel_events.append(event[:80])


def browse_offer_page(page: Page, policy: OfferFunnelPolicy) -> dict[str, Any]:
    steps: list[dict[str, Any]] = []
    opened_pages: list[Page] = []
    offer_signal = False
    _wait_for_dom(page, policy.navigation_timeout_ms)

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
            page = opened_page
            opened_pages.append(opened_page)
        steps.append(cta)
        if cta.get("status") in {"clicked", "clicked_new_page"}:
            _wait_for_dom(page, policy.navigation_timeout_ms)
            quiz = complete_quiz(page, max_questions=policy.quiz_max_questions)
            if quiz.get("status") != "not_found":
                steps.append(quiz)
                offer_signal = True
            form = find_offer_form(page)
            offer_signal = offer_signal or form is not None

    offer_signal = offer_signal or form is not None or any(
        step.get("action") == "prelander_cta"
        and step.get("status") in {"clicked", "clicked_new_page"}
        for step in steps
    )

    return {
        "status": "offer_engaged" if offer_signal else "landing_viewed",
        "form_detected": form is not None,
        "success_confirmed": False,
        "final_url": redact_url(page.url),
        "final_domain": _domain(page.url),
        "steps": steps,
        "_active_page": page,
        "_opened_pages": opened_pages,
    }


def scroll_prelander(page: Page, *, seconds: float, max_scrolls: int) -> dict[str, Any]:
    started = time.monotonic()
    scrolls = 0
    deadline = started + max(0.0, seconds)
    while scrolls < max(0, max_scrolls) and time.monotonic() < deadline:
        try:
            state = page.evaluate(
                """() => ({
                    y: window.scrollY,
                    viewport: window.innerHeight,
                    height: Math.max(document.body.scrollHeight, document.documentElement.scrollHeight),
                })"""
            )
            if state["y"] + state["viewport"] >= state["height"] - 24:
                break
            distance = max(260, round(float(state["viewport"]) * random.uniform(0.55, 0.85)))
            page.evaluate("dy => window.scrollBy({top: dy, behavior: 'smooth'})", distance)
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


def complete_quiz(page: Page, *, max_questions: int) -> dict[str, Any]:
    if find_offer_form(page) is not None:
        return {"action": "quiz", "status": "not_found", "answered": 0}
    started = _click_first_selector(page, QUIZ_START_SELECTORS) or _click_text_control(
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
        before_state = _quiz_state(page)
        answer = _first_visible_from_selectors(page, QUIZ_ANSWER_SELECTORS)
        if answer is None:
            break
        try:
            answer.scroll_into_view_if_needed(timeout=2000)
            answer.click(timeout=3000)
            answered += 1
            page.wait_for_timeout(random.randint(500, 1000))
            if find_offer_form(page) is None and not detect_success(page):
                _click_text_control(
                    page,
                    QUIZ_NEXT_TERMS,
                    excludes=CTA_EXCLUDES,
                )
            after_state = _quiz_state(page)
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


def click_prelander_cta(page: Page, *, timeout_ms: int) -> dict[str, Any]:
    before_url = page.url
    before_pages = set(page.context.pages)
    locator = _best_text_control(page, CTA_TERMS, excludes=CTA_EXCLUDES)
    if locator is None:
        return {"action": "prelander_cta", "status": "not_found"}
    try:
        label = _control_text(locator)
        locator.scroll_into_view_if_needed(timeout=3000)
        locator.click(timeout=min(max(1, timeout_ms), 8000), no_wait_after=True)
        deadline = time.monotonic() + max(0, timeout_ms) / 1000
        while time.monotonic() < deadline:
            new_pages = [candidate for candidate in page.context.pages if candidate not in before_pages]
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

    _select_phone_country(form, identity.country_code)
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

    button = _submit_button(form)
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
        success_page = _find_success_page(page, before_pages)
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


def find_offer_form(page: Page):
    for scope in [page, *[frame for frame in page.frames if frame != page.main_frame]]:
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
                    fields = _form_fields(form)
                    if {"email", "phone"}.intersection(fields):
                        return scope, form
            except PlaywrightError:
                continue
    return None


def inspect_offer_form(form) -> dict[str, Any]:
    fields = _form_fields(form)
    dangerous: list[str] = []
    try:
        for element in form.locator("input,select,textarea").all():
            metadata = _field_metadata(element)
            haystack = _fold(" ".join(str(value or "") for value in metadata.values()))
            field_type = str(metadata.get("type") or "").casefold()
            if field_type in {"password", "file"}:
                dangerous.append(field_type)
            dangerous.extend(term for term in DANGEROUS_FIELD_TERMS if term in haystack)
    except PlaywrightError:
        pass
    return {"fields": fields, "dangerous_fields": sorted(set(dangerous))}


def fill_offer_form(form, fields: dict[str, Any], identity: OfferIdentity) -> list[str]:
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


def detect_success(page: Page) -> bool:
    for scope in [page, *[frame for frame in page.frames if frame != page.main_frame]]:
        try:
            parsed = urlsplit(scope.url)
            folded_path = _fold(parsed.path)
            if any(part in folded_path for part in SUCCESS_URL_PARTS):
                return True
            body = _fold(scope.locator("body").inner_text(timeout=2000)[:12_000])
            if any(phrase in body for phrase in SUCCESS_PHRASES):
                return True
        except PlaywrightError:
            continue
    return False


def domain_allowed(url: str, allowed_domains: tuple[str, ...]) -> bool:
    host = _domain(url)
    for value in allowed_domains:
        allowed = value.strip().casefold().lstrip(".")
        if allowed and (host == allowed or host.endswith(f".{allowed}")):
            return True
    return False


def redact_url(url: str) -> str:
    try:
        parsed = urlsplit(url)
    except ValueError:
        return ""
    return urlunsplit((parsed.scheme, parsed.netloc, parsed.path, "", ""))


def redact_error(value: Any) -> str:
    text = repr(value) if isinstance(value, BaseException) else str(value)
    return URL_IN_TEXT.sub(lambda match: redact_url(match.group(0)), text)


def _form_fields(form) -> dict[str, Any]:
    fields: dict[str, Any] = {}
    try:
        elements = form.locator("input:not([type='hidden']), textarea").all()
    except PlaywrightError:
        return fields
    for element in elements:
        try:
            if not element.is_visible() or element.is_disabled() or element.is_editable() is False:
                continue
            metadata = _field_metadata(element)
            kind = _field_kind(metadata)
            if kind and kind not in fields:
                fields[kind] = element
        except PlaywrightError:
            continue
    if "full_name" in fields and "first_name" in fields:
        fields.pop("full_name", None)
    return fields


def _field_metadata(element) -> dict[str, str]:
    return element.evaluate(
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
    )


def _field_kind(metadata: dict[str, str]) -> str:
    field_type = str(metadata.get("type") or "").casefold()
    autocomplete = str(metadata.get("autocomplete") or "").casefold()
    haystack = _fold(" ".join(str(value or "") for value in metadata.values()))
    if field_type == "email" or "email" in autocomplete or any(term in haystack for term in ("email", "e-mail", "correo", "mail")):
        return "email"
    if field_type == "tel" or "tel" in autocomplete or any(term in haystack for term in ("phone", "telephone", "telefono", "mobile", "whatsapp")):
        return "phone"
    if "given-name" in autocomplete or any(term in haystack for term in ("first_name", "firstname", "first name", "fname", "nombre de pila")):
        return "first_name"
    if "family-name" in autocomplete or any(term in haystack for term in ("last_name", "lastname", "last name", "lname", "surname", "apellido")):
        return "last_name"
    if autocomplete == "name" or any(term in haystack for term in ("full_name", "fullname", "full name", "your name")):
        return "full_name"
    name = _fold(str(metadata.get("name") or ""))
    placeholder = _fold(str(metadata.get("placeholder") or ""))
    if name in {"name", "nombre"} or placeholder in {"name", "nombre", "nome"}:
        return "first_name"
    return ""


def _submit_button(form):
    selectors = (
        "button[type='submit']",
        "input[type='submit']",
        "button:not([type])",
        "[class*='submit']",
        "[id*='submit']",
    )
    return _first_visible_from_selectors(form, selectors)


def _best_text_control(scope, terms: tuple[str, ...], *, excludes: tuple[str, ...]):
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
            text = _fold(_control_text(control))
            if (
                not text
                or len(text) > 100
                or any(term in text for term in excludes)
            ):
                continue
            score = max((len(term) for term in terms if term in text), default=-1)
            if score > best_score:
                best, best_score = control, score
        except PlaywrightError:
            continue
    return best


def _click_text_control(scope, terms: tuple[str, ...], *, excludes: tuple[str, ...]) -> bool:
    control = _best_text_control(scope, terms, excludes=excludes)
    if control is None:
        return False
    try:
        control.scroll_into_view_if_needed(timeout=2000)
        control.click(timeout=3000)
        scope.wait_for_timeout(random.randint(400, 800))
        return True
    except PlaywrightError:
        return False


def _click_first_selector(scope, selectors: tuple[str, ...]) -> bool:
    control = _first_visible_from_selectors(scope, selectors)
    if control is None:
        return False
    try:
        control.scroll_into_view_if_needed(timeout=2000)
        control.click(timeout=3000)
        scope.wait_for_timeout(random.randint(400, 800))
        return True
    except PlaywrightError:
        return False


def _first_visible_from_selectors(scope, selectors: tuple[str, ...]):
    for selector in selectors:
        try:
            for locator in scope.locator(selector).all():
                if locator.is_visible():
                    return locator
        except PlaywrightError:
            continue
    return None


def _control_text(control) -> str:
    return str(
        control.evaluate(
            "el => el.innerText || el.value || el.getAttribute('aria-label') || ''"
        )
        or ""
    ).strip()


def _wait_for_dom(page: Page, timeout_ms: int) -> None:
    try:
        page.wait_for_load_state("domcontentloaded", timeout=max(1, timeout_ms))
    except PlaywrightError:
        pass


def _funnel_status(result: dict[str, Any]) -> str:
    if result.get("success_confirmed"):
        return "success_confirmed"
    form_status = str(result.get("form_status") or "")
    if form_status in {"filled_not_submitted", "detected", "submit_domain_not_allowed"}:
        return "form_ready"
    if form_status.startswith("submitted_"):
        return "form_submitted_unconfirmed"
    if form_status == "blocked_dangerous_fields":
        return "unsafe_form_blocked"
    return str(result.get("status") or "offer_engaged")


def _target_key(target: CalibrationTarget, url: str) -> str:
    return str(target.fb_ad_id or target.landing_clean or redact_url(url)).casefold()


def public_offer_target(target: CalibrationTarget) -> dict[str, Any]:
    return {
        "advertiser": target.advertiser,
        "country": target.country,
        "fb_ad_id": target.fb_ad_id,
        "facebook_post_url": redact_url(target.facebook_post_url or ""),
        "landing_domain": _domain(offer_url(target)),
    }


def offer_url(target: CalibrationTarget) -> str:
    for candidate in (
        target.landing_full,
        target.cta_href,
        target.landing_clean,
    ):
        value = str(candidate or "").strip()
        if _external_http_url(value):
            return value
    return ""


def _select_identity_payload(
    payload: dict[str, Any],
    *,
    profile_uuid: str,
    country: str | None,
) -> dict[str, Any]:
    if any(key in payload for key in ("first_name", "email", "phone")):
        return payload
    profiles = payload.get("profiles")
    if isinstance(profiles, dict):
        profile = profiles.get(profile_uuid)
        if isinstance(profile, dict):
            return profile
    countries = payload.get("countries")
    if isinstance(countries, dict) and country:
        wanted = country.strip().casefold()
        for key, value in countries.items():
            if str(key).strip().casefold() == wanted and isinstance(value, dict):
                return value
    default = payload.get("default")
    if isinstance(default, dict):
        return default
    return {}


def _select_phone_country(form, country_code: str) -> bool:
    wanted = country_code.strip().casefold()
    if not wanted:
        return False
    try:
        root = form.locator("xpath=ancestor-or-self::*[contains(@class, 'iti')][1]")
        scope = root.first if root.count() else form
        dropdown = _first_visible_from_selectors(scope, PHONE_DROPDOWN_SELECTORS)
        if dropdown is None:
            dropdown = _first_visible_from_selectors(
                form.page,
                PHONE_DROPDOWN_SELECTORS,
            )
        if dropdown is None:
            return False
        dropdown.click(timeout=3000)
        page = form.page
        for selector in PHONE_COUNTRY_SELECTORS:
            candidate = page.locator(
                f"{selector}[data-country-code='{wanted}']"
            ).first
            if candidate.count() and candidate.is_visible():
                candidate.click(timeout=3000)
                return True
    except PlaywrightError:
        return False
    return False


def _quiz_state(page: Page) -> tuple[str, ...]:
    values: list[str] = []
    for selector in QUIZ_ANSWER_SELECTORS:
        try:
            for locator in page.locator(selector).all():
                if locator.is_visible():
                    values.append(_fold(_control_text(locator))[:120])
        except PlaywrightError:
            continue
    return tuple(value for value in values if value)


def _find_success_page(page: Page, before_pages: set[Page]) -> Page | None:
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


def _public_action(action: dict[str, Any]) -> dict[str, Any]:
    public: dict[str, Any] = {}
    for key, value in action.items():
        if isinstance(value, str) and (key == "href" or key.endswith("_url")):
            public[key] = redact_url(value)
        elif isinstance(value, str) and "error" in key:
            public[key] = redact_error(value)
        else:
            public[key] = value
    return public


def _goto_direct_offer(page: Page, url: str, *, timeout_ms: int):
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


def _has_offer_signal(page: Page) -> bool:
    if find_offer_form(page) is not None:
        return True
    if _first_visible_from_selectors(page, QUIZ_START_SELECTORS) is not None:
        return True
    return _best_text_control(page, CTA_TERMS, excludes=CTA_EXCLUDES) is not None


def _same_site(left: str, right: str) -> bool:
    if not left or not right:
        return False
    return (
        left == right
        or left.endswith(f".{right}")
        or right.endswith(f".{left}")
    )


def _external_http_url(url: str) -> bool:
    try:
        parsed = urlsplit(url)
    except ValueError:
        return False
    return parsed.scheme in {"http", "https"} and bool(parsed.hostname)


def _domain(url: str) -> str:
    try:
        return (urlsplit(url).hostname or "").casefold()
    except ValueError:
        return ""


def _fold(value: str) -> str:
    normalized = unicodedata.normalize("NFKD", value.casefold())
    return " ".join(
        "".join(char for char in normalized if not unicodedata.combining(char)).split()
    )


def _close_pages(pages: list[Page]) -> None:
    for page in pages:
        try:
            if not page.is_closed():
                page.close(run_before_unload=False)
        except PlaywrightError:
            pass

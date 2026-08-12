from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from playwright.sync_api import BrowserContext, Page

from ....adapters.playwright import open_ad_landing
from ....planning import CalibrationTarget
from ...models import OfferFunnelPolicy
from ...security import (
    domain,
    external_http_url,
    redact_error,
    redact_url,
    same_site,
)
from ...targets import offer_url
from .browser import close_pages, goto_direct_offer, public_action


@dataclass(slots=True)
class OpenedLanding:
    page: Page | None
    opened_pages: list[Page]
    result: dict[str, Any]


def open_funnel_landing(
    context: BrowserContext,
    policy: OfferFunnelPolicy,
    target: CalibrationTarget,
    *,
    source_page: Page | None,
    element_id: str,
) -> OpenedLanding:
    if source_page is not None and element_id:
        click_result, landing_page, opened_pages = open_ad_landing(
            source_page,
            element_id,
            cta=target.cta,
            expected_url=target.landing_full or target.landing_clean or "",
            timeout_ms=policy.navigation_timeout_ms,
        )
        click_result = public_action(click_result)
        click_result["opening"] = "facebook_cta"
        if landing_page is not None and click_result.get("status") == "visited":
            mismatch = click_result.get("expected_domain_match") is False
            if not mismatch:
                return OpenedLanding(landing_page, opened_pages, click_result)
            click_result["status"] = "cta_domain_mismatch"
        close_pages(opened_pages)
        if not policy.direct_offer_fallback:
            return OpenedLanding(source_page, [], click_result)
        fallback_reason = str(click_result.get("status") or "facebook_cta_failed")
    else:
        click_result = None
        fallback_reason = "facebook_post_unavailable"

    if not policy.direct_offer_fallback:
        fallback = {
            "action": "landing_open",
            "status": "direct_fallback_disabled",
            "opening": "none",
        }
        return OpenedLanding(source_page, [], fallback)

    direct_url = offer_url(target)
    if not external_http_url(direct_url):
        fallback = {
            "action": "landing_open",
            "status": "missing_direct_offer_url",
            "opening": "direct_offer",
        }
        return OpenedLanding(source_page, [], fallback)

    page = context.new_page()
    try:
        response = goto_direct_offer(
            page,
            direct_url,
            timeout_ms=policy.navigation_timeout_ms,
        )
        status_code = response.status if response else None
        if status_code is not None and status_code >= 400:
            raise RuntimeError(f"direct offer returned HTTP {status_code}")
        source_domain = domain(direct_url)
        final_domain = domain(page.url)
        direct_result = {
            "action": "landing_open",
            "status": "visited",
            "opening": "direct_offer",
            "url": redact_url(page.url),
            "domain": final_domain,
            "source_domain": source_domain,
            "cross_domain_redirect": not same_site(
                source_domain,
                final_domain,
            ),
            "http_status": status_code,
            "fallback_reason": fallback_reason,
        }
        if click_result is not None:
            direct_result["facebook_cta_attempt"] = click_result
        return OpenedLanding(page, [page], direct_result)
    except Exception as exc:
        close_pages([page])
        return OpenedLanding(
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

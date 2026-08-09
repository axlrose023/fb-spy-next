from __future__ import annotations

from typing import Any

from ..planning import CalibrationTarget
from .security import domain, external_http_url, redact_url


def target_key(target: CalibrationTarget, url: str) -> str:
    return str(target.fb_ad_id or target.landing_clean or redact_url(url)).casefold()


def public_offer_target(target: CalibrationTarget) -> dict[str, Any]:
    return {
        "advertiser": target.advertiser,
        "country": target.country,
        "fb_ad_id": target.fb_ad_id,
        "facebook_post_url": redact_url(target.facebook_post_url or ""),
        "landing_domain": domain(offer_url(target)),
    }


def offer_url(target: CalibrationTarget) -> str:
    for candidate in (
        target.landing_full,
        target.cta_href,
        target.landing_clean,
    ):
        value = str(candidate or "").strip()
        if external_http_url(value):
            return value
    return ""

from __future__ import annotations

import re
from typing import Any

from .matching import hostname


def apply_prefilter_uncertainty_guard(
    raw: dict[str, Any],
    data: dict[str, Any],
) -> dict[str, Any]:
    """Hold visually incomplete link cards for cookie-free evidence resolution."""
    if data.get("result") != "not_relevant":
        return data
    if str(raw.get("ad_type") or "").casefold() != "link":
        return data

    displayed_domain = hostname(raw.get("displayed_domain"))
    if not displayed_domain:
        return data
    headline = str(raw.get("headline") or "").strip().casefold()
    normalized_headline = hostname(headline)
    domain_only_headline = not headline or normalized_headline == displayed_domain
    missing_copy = not str(raw.get("ad_text") or "").strip()
    missing_cta = not str(raw.get("cta") or "").strip()
    creative = str(raw.get("creative_img") or "")
    avatar_only = (
        not creative
        or bool(re.search(r"/v/t\d+\.\d+-1/", creative))
        or bool(
            re.search(
                r"(?:^|[_=&])p(?:135|160|180|240)x(?:135|160|180|240)",
                creative,
            )
        )
    )
    screenshot_issue = str(raw.get("screenshot_issue") or "").casefold()
    visibly_incomplete = screenshot_issue in {
        "blank_media",
        "viewport_fallback",
    } or avatar_only
    has_recovery_handle = bool(
        str(raw.get("cta_href") or "").strip()
        or str(raw.get("facebook_post_url") or "").strip()
    )
    if not (
        domain_only_headline
        and missing_copy
        and missing_cta
        and visibly_incomplete
        and has_recovery_handle
    ):
        return data

    guarded = dict(data)
    guarded["result"] = "uncertain"
    guarded["reason"] = (
        "The Facebook link card is visually incomplete and contains only an "
        "advertiser/domain shell; resolve its passive CTA URL in an isolated "
        "cookie-free browser before making a final decision."
    )
    guarded["prefilter_original_result"] = "not_relevant"
    if data.get("reason"):
        guarded["prefilter_original_reason"] = str(data["reason"])
    return guarded

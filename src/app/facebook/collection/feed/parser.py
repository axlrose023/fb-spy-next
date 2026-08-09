from __future__ import annotations

from typing import Any

from ..models import CollectedAd


def ad_from_detection(
    raw: dict[str, Any],
    *,
    country: str | None,
) -> CollectedAd:
    return CollectedAd(
        advertiser=str(raw["advertiser"]),
        ad_type=str(raw["ad_type"]),
        has_video=bool(raw.get("has_video")),
        country=country,
        displayed_domain=str(raw["domain"]),
        headline=str(raw["headline"]),
        ad_text=str(raw["ad_text"]),
        cta=str(raw["cta"]),
        cta_href=str(raw.get("cta_href") or ""),
        creative_img=str(raw["creative_img"]),
        feed_element_id=_optional(raw.get("element_id")),
        fb_ad_id=_optional(raw.get("fb_ad_id")),
        facebook_page_url=_optional(raw.get("facebook_page_url")),
        facebook_post_url=_optional(raw.get("facebook_post_url")),
    )


def _optional(value: Any) -> str | None:
    candidate = str(value or "").strip()
    return candidate or None

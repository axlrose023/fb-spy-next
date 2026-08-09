from __future__ import annotations

from dataclasses import fields
from typing import Any

from app.services import facebook_runner
from app.services.facebook.calibration import CalibrationTarget


def ad_from_raw(raw: dict[str, Any], *, element_id: str) -> facebook_runner.Ad:
    values = {
        field.name: raw.get(field.name)
        for field in fields(facebook_runner.Ad)
        if field.name in raw
    }
    values["advertiser"] = str(raw.get("advertiser") or "")
    values["ad_type"] = str(raw.get("ad_type") or "in_facebook")
    for name in (
        "displayed_domain",
        "headline",
        "ad_text",
        "cta",
        "cta_href",
        "creative_img",
        "video",
        "screenshot",
        "screenshot_issue",
    ):
        values[name] = str(raw.get(name) or "")
    values["has_video"] = bool(raw.get("has_video"))
    values["screenshot_ok"] = raw.get("screenshot_ok") is not False
    values["utm"] = raw.get("utm") if isinstance(raw.get("utm"), dict) else {}
    values["feed_element_id"] = element_id
    return facebook_runner.Ad(**values)  # type: ignore[arg-type]


def target_from_raw(raw: dict[str, Any], post_url: str) -> CalibrationTarget:
    return CalibrationTarget(
        url=post_url,
        advertiser=str(raw.get("advertiser") or ""),
        displayed_domain=str(raw.get("displayed_domain") or ""),
        headline=str(raw.get("headline") or ""),
        ad_text=str(raw.get("ad_text") or ""),
        cta=str(raw.get("cta") or ""),
        country=clean(raw.get("country")),
        fb_ad_id=clean(raw.get("fb_ad_id")),
        facebook_page_url=clean(raw.get("facebook_page_url")),
        facebook_post_url=post_url,
        landing_clean=clean(raw.get("landing_clean")),
        creative_img=clean(raw.get("creative_img")),
    )


def merge_ad_fields(raw: dict[str, Any], ad: facebook_runner.Ad) -> None:
    for field in fields(facebook_runner.Ad):
        raw[field.name] = getattr(ad, field.name)


def clean(value: Any) -> str | None:
    candidate = str(value or "").strip()
    return candidate or None

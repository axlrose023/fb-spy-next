from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any
from urllib.parse import urlsplit


@dataclass
class CalibrationTarget:
    url: str
    advertiser: str = ""
    displayed_domain: str = ""
    headline: str = ""
    ad_text: str = ""
    cta: str = ""
    cta_href: str | None = None
    country: str | None = None
    fb_ad_id: str | None = None
    feed_element_id: str | None = None
    facebook_page_url: str | None = None
    facebook_post_url: str | None = None
    landing_full: str | None = None
    landing_clean: str | None = None
    creative_img: str | None = None
    source: str = ""
    source_index: int | None = None
    run_id: str | None = None
    captured_at: str | None = None

    @property
    def domain_key(self) -> str:
        return domain_key(self.landing_clean or self.url or self.displayed_domain)


def rotate_calibration_targets(
    targets: list[CalibrationTarget],
    offset: int,
) -> list[CalibrationTarget]:
    if not targets:
        return []
    normalized_offset = max(0, offset) % len(targets)
    if normalized_offset == 0:
        return list(targets)
    return [*targets[normalized_offset:], *targets[:normalized_offset]]


def select_calibration_targets(
    raw_ads: list[dict[str, Any]],
    *,
    country: str | None = None,
    limit: int = 20,
    max_per_domain: int = 2,
    include_creative_fallback: bool = False,
) -> list[CalibrationTarget]:
    normalized_country = normalize_filter(country)
    candidates: list[tuple[int, datetime, CalibrationTarget]] = []
    seen_keys: set[str] = set()
    seen_landing_keys: set[str] = set()

    for raw in raw_ads:
        if normalized_country and normalize_filter(raw.get("country")) != (
            normalized_country
        ):
            continue
        url = target_url(raw, include_creative_fallback=include_creative_fallback)
        if not url:
            continue
        target = _target_from_raw(raw, url)
        unique_key = _unique_key(target)
        landing_key = target.landing_clean or target.url
        if unique_key in seen_keys or (
            not target.fb_ad_id and landing_key in seen_landing_keys
        ):
            continue
        seen_keys.add(unique_key)
        seen_landing_keys.add(landing_key)
        candidates.append((_target_score(raw), captured_at(raw), target))

    candidates.sort(key=lambda item: (item[0], item[1]), reverse=True)
    return _limit_by_domain(
        [target for _, _, target in candidates],
        limit=limit,
        max_per_domain=max_per_domain,
    )


def target_url(raw: dict[str, Any], *, include_creative_fallback: bool) -> str:
    for key in ("landing_full", "landing_clean"):
        value = clean(raw.get(key))
        if value:
            return value
    if include_creative_fallback:
        return clean(raw.get("creative_img")) or ""
    return ""


def normalize_filter(value: Any) -> str | None:
    cleaned = clean(value)
    return cleaned.casefold() if cleaned else None


def clean(value: Any) -> str | None:
    if value is None:
        return None
    cleaned = str(value).strip()
    return cleaned or None


def int_or_none(value: Any) -> int | None:
    try:
        return int(value) if value is not None else None
    except (TypeError, ValueError):
        return None


def domain_key(value: str) -> str:
    if not value:
        return ""
    candidate = f"https://{value}" if "://" not in value and "." in value else value
    try:
        host = urlsplit(candidate).netloc or urlsplit(f"https://{candidate}").netloc
    except ValueError:
        return candidate.lower().strip()
    return host.lower().removeprefix("www.")


def captured_at(raw: dict[str, Any]) -> datetime:
    value = clean(raw.get("captured_at"))
    if not value:
        return datetime.min
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00")).replace(tzinfo=None)
    except ValueError:
        return datetime.min


def _target_from_raw(raw: dict[str, Any], url: str) -> CalibrationTarget:
    return CalibrationTarget(
        url=url,
        advertiser=str(raw.get("advertiser") or ""),
        displayed_domain=str(raw.get("displayed_domain") or ""),
        headline=str(raw.get("headline") or ""),
        ad_text=str(raw.get("ad_text") or ""),
        cta=str(raw.get("cta") or ""),
        cta_href=clean(raw.get("cta_href")),
        country=clean(raw.get("country")),
        fb_ad_id=clean(raw.get("fb_ad_id")),
        feed_element_id=clean(raw.get("feed_element_id")),
        facebook_page_url=clean(raw.get("facebook_page_url")),
        facebook_post_url=clean(raw.get("facebook_post_url")),
        landing_full=clean(raw.get("landing_full")),
        landing_clean=clean(raw.get("landing_clean")),
        creative_img=clean(raw.get("creative_img")),
        source=str(raw.get("_source") or ""),
        source_index=int_or_none(raw.get("_source_index") or raw.get("source_index")),
        run_id=clean(raw.get("run_id")),
        captured_at=clean(raw.get("captured_at")),
    )


def _target_score(raw: dict[str, Any]) -> int:
    return (
        (5 if raw.get("landing_full") else 0)
        + (2 if raw.get("fb_ad_id") else 0)
        + (1 if raw.get("headline") or raw.get("ad_text") else 0)
        + (1 if raw.get("has_video") else 0)
    )


def _limit_by_domain(
    targets: list[CalibrationTarget],
    *,
    limit: int,
    max_per_domain: int,
) -> list[CalibrationTarget]:
    if limit <= 0:
        return []
    domain_counts: dict[str, int] = {}
    selected: list[CalibrationTarget] = []
    overflow: list[CalibrationTarget] = []
    per_domain = max(1, max_per_domain)
    for target in targets:
        domain = target.domain_key or target.displayed_domain or target.url
        count = domain_counts.get(domain, 0)
        if count < per_domain:
            selected.append(target)
            domain_counts[domain] = count + 1
        else:
            overflow.append(target)
        if len(selected) >= limit:
            return selected
    return [*selected, *overflow][:limit]


def _unique_key(target: CalibrationTarget) -> str:
    if target.fb_ad_id:
        return f"fb_ad_id:{target.fb_ad_id}"
    if target.landing_clean:
        return f"landing_clean:{target.landing_clean}"
    return f"url:{target.url}"

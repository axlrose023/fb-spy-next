from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from ...planning import CalibrationTarget, select_calibration_targets
from .target_mapping import (
    clean,
    normalize_filter,
    raw_is_relevant,
    target_url,
    valid_facebook_post_url,
)


def load_targets_from_ads_json(
    ads_json_paths: list[Path],
    *,
    country: str | None = None,
    limit: int = 20,
    max_per_domain: int = 2,
    include_creative_fallback: bool = False,
    require_relevant: bool = False,
) -> list[CalibrationTarget]:
    raw_ads: list[dict[str, Any]] = []
    for ads_json_path in ads_json_paths:
        path = ads_json_path.expanduser().resolve()
        payload = _read_ads(path)
        for index, raw in enumerate(payload, start=1):
            if not isinstance(raw, dict):
                continue
            if require_relevant and not raw_is_relevant(raw):
                continue
            item = dict(raw)
            item.setdefault("_source", str(path))
            item.setdefault("_source_index", index)
            raw_ads.append(item)

    targets: list[CalibrationTarget] = select_calibration_targets(
        raw_ads,
        country=country,
        limit=limit,
        max_per_domain=max_per_domain,
        include_creative_fallback=include_creative_fallback,
    )
    return targets


def load_engagement_targets_from_ads_json(
    ads_json_paths: list[Path],
    *,
    country: str | None = None,
    limit: int = 1000,
) -> list[CalibrationTarget]:
    normalized_country = normalize_filter(country)
    targets: list[CalibrationTarget] = []
    seen: set[str] = set()
    for ads_json_path in ads_json_paths:
        path = ads_json_path.expanduser().resolve()
        for index, raw in enumerate(_read_ads(path), start=1):
            if not isinstance(raw, dict) or not raw_is_relevant(raw):
                continue
            if (
                normalized_country
                and normalize_filter(raw.get("country")) != normalized_country
            ):
                continue
            target = _engagement_target(raw, path, index)
            key = str(
                target.fb_ad_id
                or target.landing_clean
                or "\x1f".join(
                    (
                        target.advertiser.casefold(),
                        target.displayed_domain.casefold(),
                        target.headline.casefold(),
                        target.ad_text.casefold(),
                    )
                )
            )
            if not key.strip("\x1f") or key in seen:
                continue
            seen.add(key)
            targets.append(target)
            if len(targets) >= limit:
                return targets
    return targets


def load_saved_facebook_targets_from_ads_json(
    ads_json_paths: list[Path],
    *,
    country: str | None = None,
    limit: int = 20,
    excluded_urls: set[str] | None = None,
    include_direct_offers: bool = False,
) -> list[CalibrationTarget]:
    """Load relevant saved posts, optionally retaining direct-offer fallbacks."""
    if limit <= 0:
        return []
    normalized_country = normalize_filter(country)
    excluded = excluded_urls or set()
    targets: list[CalibrationTarget] = []
    seen_targets: set[str] = set()
    for ads_json_path in ads_json_paths:
        path = ads_json_path.expanduser().resolve()
        for index, raw in enumerate(_read_ads(path), start=1):
            if not isinstance(raw, dict) or not raw_is_relevant(raw):
                continue
            if (
                normalized_country
                and normalize_filter(raw.get("country")) != normalized_country
            ):
                continue
            post_url = valid_facebook_post_url(raw.get("facebook_post_url"))
            cta_href = clean(raw.get("cta_href"))
            landing_full = clean(raw.get("landing_full"))
            landing_clean = clean(raw.get("landing_clean"))
            if post_url in excluded:
                post_url = ""
            if not post_url and not (
                include_direct_offers and (landing_full or cta_href or landing_clean)
            ):
                continue
            target_key = str(
                post_url
                or raw.get("fb_ad_id")
                or landing_clean
                or cta_href
                or landing_full
            )
            if not target_key or target_key in seen_targets:
                continue
            seen_targets.add(target_key)
            targets.append(
                _saved_target(
                    raw,
                    path,
                    index,
                    post_url=post_url,
                    cta_href=cta_href,
                    landing_full=landing_full,
                    landing_clean=landing_clean,
                )
            )
            if len(targets) >= limit:
                return targets
    return targets


def _engagement_target(
    raw: dict[str, Any],
    path: Path,
    index: int,
) -> CalibrationTarget:
    return CalibrationTarget(
        url=target_url(raw, include_creative_fallback=False),
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
        source=str(path),
        source_index=index,
        run_id=clean(raw.get("run_id")),
        captured_at=clean(raw.get("captured_at")),
    )


def _saved_target(
    raw: dict[str, Any],
    path: Path,
    index: int,
    *,
    post_url: str,
    cta_href: str | None,
    landing_full: str | None,
    landing_clean: str | None,
) -> CalibrationTarget:
    return CalibrationTarget(
        url=post_url or landing_full or cta_href or landing_clean or "",
        advertiser=str(raw.get("advertiser") or ""),
        displayed_domain=str(raw.get("displayed_domain") or ""),
        headline=str(raw.get("headline") or ""),
        ad_text=str(raw.get("ad_text") or ""),
        cta=str(raw.get("cta") or ""),
        cta_href=cta_href,
        country=clean(raw.get("country")),
        fb_ad_id=clean(raw.get("fb_ad_id")),
        feed_element_id=None,
        facebook_page_url=clean(raw.get("facebook_page_url")),
        facebook_post_url=post_url or None,
        landing_full=landing_full,
        landing_clean=landing_clean,
        creative_img=clean(raw.get("creative_img")),
        source=str(path),
        source_index=index,
        run_id=clean(raw.get("run_id")),
        captured_at=clean(raw.get("captured_at")),
    )


def _read_ads(path: Path) -> list[Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, list):
        raise ValueError(f"Expected a JSON list: {path}")
    return payload

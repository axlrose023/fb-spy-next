from __future__ import annotations

from typing import Any
from urllib.parse import parse_qs, urlparse


def is_relevant_ad(raw: dict[str, Any]) -> bool:
    relevance = raw.get("relevance")
    return bool(
        raw.get("relevant") is True
        or (isinstance(relevance, dict) and relevance.get("result") == "relevant")
        or (isinstance(relevance, str) and relevance.casefold() == "relevant")
    )


def is_direct_calibration_target(raw: dict[str, Any]) -> bool:
    post_url = str(raw.get("facebook_post_url") or "")
    try:
        parsed = urlparse(post_url)
    except ValueError:
        return False
    host = (parsed.hostname or "").casefold()
    query = parse_qs(parsed.query)
    facebook_host = host == "facebook.com" or host.endswith(".facebook.com")
    direct_path = "/posts/" in parsed.path
    direct_query = (
        parsed.path.rstrip("/").endswith(("story.php", "permalink.php"))
        and bool((query.get("story_fbid") or [""])[0])
        and bool((query.get("id") or [""])[0])
    )
    direct_post = facebook_host and (direct_path or direct_query)

    direct_offer = str(raw.get("landing_full") or raw.get("landing_clean") or "")
    try:
        offer = urlparse(direct_offer)
        usable_offer = offer.scheme in {"http", "https"} and bool(offer.hostname)
    except ValueError:
        usable_offer = False
    return is_relevant_ad(raw) and (direct_post or usable_offer)


def merge_calibration_ads(
    fresh: list[Any],
    previous: list[Any],
    *,
    limit: int = 1000,
) -> list[dict[str, Any]]:
    if limit <= 0:
        return []
    candidates = [
        item
        for item in [*fresh, *previous]
        if isinstance(item, dict) and is_direct_calibration_target(item)
    ]
    unique: list[dict[str, Any]] = []
    seen: set[str] = set()
    for index, item in enumerate(candidates):
        key = str(
            item.get("facebook_post_url")
            or item.get("fb_ad_id")
            or item.get("landing_clean")
            or item.get("landing_full")
            or item.get("screenshot")
            or f"item:{index}"
        )
        if key in seen:
            continue
        seen.add(key)
        unique.append(item)
        if len(unique) >= limit:
            break
    return unique


def calibration_pool_name(value: str) -> str:
    name = "".join(
        char.lower() if char.isascii() and char.isalnum() else "_" for char in value
    )
    return "_".join(part for part in name.split("_") if part) or "unknown"

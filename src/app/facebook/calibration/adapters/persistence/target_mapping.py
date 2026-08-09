from __future__ import annotations

from typing import Any
from urllib.parse import parse_qs, urlsplit


def target_url(
    raw: dict[str, Any],
    *,
    include_creative_fallback: bool,
) -> str:
    for key in ("landing_full", "landing_clean"):
        value = clean(raw.get(key))
        if value:
            return value
    if include_creative_fallback:
        return clean(raw.get("creative_img")) or ""
    return ""


def valid_facebook_post_url(value: Any) -> str:
    url = clean(value)
    if not url:
        return ""
    try:
        parsed = urlsplit(url)
    except ValueError:
        return ""
    host = (parsed.hostname or "").casefold()
    if host != "facebook.com" and not host.endswith(".facebook.com"):
        return ""
    parts = [part for part in parsed.path.split("/") if part]
    if "posts" in parts:
        index = parts.index("posts")
        return url if index > 0 and index + 1 < len(parts) else ""
    query = parse_qs(parsed.query)
    if (
        parsed.path.rstrip("/").endswith(("story.php", "permalink.php"))
        and (query.get("story_fbid") or [""])[0]
        and (query.get("id") or [""])[0]
    ):
        return url
    return ""


def normalize_filter(value: Any) -> str | None:
    value = clean(value)
    return value.casefold() if value else None


def raw_is_relevant(raw: dict[str, Any]) -> bool:
    if raw.get("relevant") is True:
        return True
    relevance = raw.get("relevance")
    if isinstance(relevance, dict):
        return str(relevance.get("result") or "").casefold() == "relevant"
    if isinstance(relevance, str):
        return relevance.casefold() == "relevant"
    return False


def clean(value: Any) -> str | None:
    if value is None:
        return None
    value = str(value).strip()
    return value or None

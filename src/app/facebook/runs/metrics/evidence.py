from __future__ import annotations

from typing import Any
from urllib.parse import urlsplit

from .normalization import clean


def count_by(ads: list[dict[str, Any]], key: str) -> dict[str, int]:
    counts: dict[str, int] = {}
    for ad in ads:
        value = clean(ad.get(key)) or ""
        counts[value] = counts.get(value, 0) + 1
    return counts


def counts(values: list[str]) -> dict[str, int]:
    result: dict[str, int] = {}
    for value in values:
        result[value] = result.get(value, 0) + 1
    return result


def domain_value(ad: dict[str, Any]) -> str:
    return (
        clean(
            ad.get("landing_clean")
            or ad.get("landing_full")
            or ad.get("displayed_domain")
        )
        or ""
    )


def domain_key(value: str) -> str:
    if not value:
        return ""
    candidate = value if "://" in value else f"https://{value}"
    try:
        host = urlsplit(candidate).netloc
    except ValueError:
        return value.lower().strip()
    return host.lower().removeprefix("www.")


def clean_landing_key(value: Any) -> str:
    text = clean(value)
    if not text:
        return ""
    try:
        parsed = urlsplit(text)
    except ValueError:
        return text
    return f"{parsed.scheme}://{parsed.netloc.lower()}{parsed.path}".rstrip("/")


def has_relevance(ad: dict[str, Any]) -> bool:
    if isinstance(ad.get("relevant"), bool):
        return True
    relevance = ad.get("relevance")
    if isinstance(relevance, dict):
        return str(relevance.get("result") or "").casefold() in {
            "relevant",
            "not_relevant",
        }
    if isinstance(relevance, str):
        return relevance.casefold() in {"relevant", "not_relevant"}
    return False


def is_relevant(ad: dict[str, Any]) -> bool:
    if ad.get("relevant") is True:
        return True
    relevance = ad.get("relevance")
    if isinstance(relevance, dict):
        return str(relevance.get("result") or "").casefold() == "relevant"
    if isinstance(relevance, str):
        return relevance.casefold() == "relevant"
    return False

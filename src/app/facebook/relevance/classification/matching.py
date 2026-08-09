from __future__ import annotations

import re
from typing import Any
from urllib.parse import urlparse


def contains_term(text: str, term: str) -> bool:
    """Match words and phrases without matching fragments inside words."""
    candidate = term.strip().casefold()
    if not candidate:
        return False
    if candidate in {"$", "₺"}:
        return candidate in text

    prefix = candidate.endswith("*")
    if prefix:
        candidate = candidate[:-1]
    words = re.findall(r"\w+", candidate, flags=re.UNICODE)
    if not words:
        return candidate in text.casefold()

    pattern = r"(?<!\w)" + r"[\W_]+".join(re.escape(word) for word in words)
    if not prefix:
        pattern += r"(?!\w)"
    return re.search(pattern, text.casefold(), flags=re.UNICODE) is not None


def contains_any_term(text: str, terms: tuple[str, ...]) -> bool:
    return any(contains_term(text, term) for term in terms)


def has_percentage_bonus(text: str) -> bool:
    return (
        re.search(
            r"(?<!\w)\d{1,3}\s*%\s*(?:extra|bonus|bono)(?!\w)",
            text.casefold(),
            flags=re.UNICODE,
        )
        is not None
    )


def hostname(value: Any) -> str:
    candidate = str(value or "").strip()
    if not candidate:
        return ""
    parsed = urlparse(candidate if "://" in candidate else f"//{candidate}")
    return (parsed.hostname or "").casefold().removeprefix("www.")


def advertiser_matches_domain(advertiser: Any, domain: Any) -> bool:
    host = hostname(domain)
    if not host:
        return False
    advertiser_tokens = re.findall(
        r"[\w]+", str(advertiser or "").casefold(), flags=re.UNICODE
    )
    advertiser_compact = "".join(advertiser_tokens)
    labels = [
        "".join(re.findall(r"[\w]+", label, flags=re.UNICODE))
        for label in host.split(".")[:-1]
    ]
    generic_labels = {
        "www",
        "lp",
        "go",
        "app",
        "apps",
        "ad",
        "ads",
        "link",
        "links",
        "landing",
        "try",
        "get",
        "m",
    }
    brand_labels = [
        label for label in labels if len(label) >= 4 and label not in generic_labels
    ]
    if any(
        label in advertiser_compact or advertiser_compact in label
        for label in brand_labels
        if advertiser_compact
    ):
        return True
    if any(
        token == label
        for token in advertiser_tokens
        for label in brand_labels
        if len(token) >= 4
    ):
        return True
    host_compact = "".join(re.findall(r"[\w]+", host, flags=re.UNICODE))
    token_matches = [
        token
        for token in advertiser_tokens
        if len(token) >= 2 and token in host_compact
    ]
    return len(token_matches) >= 2 and any(
        len(token) >= 4 for token in token_matches
    )

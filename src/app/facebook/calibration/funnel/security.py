from __future__ import annotations

import re
import unicodedata
from typing import Any
from urllib.parse import urlsplit, urlunsplit

URL_IN_TEXT = re.compile(r"https?://[^\s\"'<>]+", re.IGNORECASE)


def domain_allowed(url: str, allowed_domains: tuple[str, ...]) -> bool:
    host = domain(url)
    for value in allowed_domains:
        allowed = value.strip().casefold().lstrip(".")
        if allowed and (host == allowed or host.endswith(f".{allowed}")):
            return True
    return False


def redact_url(url: str) -> str:
    try:
        parsed = urlsplit(url)
    except ValueError:
        return ""
    return urlunsplit((parsed.scheme, parsed.netloc, parsed.path, "", ""))


def redact_error(value: Any) -> str:
    text = repr(value) if isinstance(value, BaseException) else str(value)
    return URL_IN_TEXT.sub(lambda match: redact_url(match.group(0)), text)


def same_site(left: str, right: str) -> bool:
    if not left or not right:
        return False
    return left == right or left.endswith(f".{right}") or right.endswith(f".{left}")


def external_http_url(url: str) -> bool:
    try:
        parsed = urlsplit(url)
    except ValueError:
        return False
    return parsed.scheme in {"http", "https"} and bool(parsed.hostname)


def domain(url: str) -> str:
    try:
        return (urlsplit(url).hostname or "").casefold()
    except ValueError:
        return ""


def fold(value: str) -> str:
    normalized = unicodedata.normalize("NFKD", value.casefold())
    return " ".join(
        "".join(char for char in normalized if not unicodedata.combining(char)).split()
    )

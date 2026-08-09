from __future__ import annotations

from typing import Any
from urllib.parse import urlparse


def is_facebook_url(value: str) -> bool:
    try:
        host = (urlparse(value).hostname or "").casefold()
    except ValueError:
        return False
    return host == "facebook.com" or host.endswith(".facebook.com")


def valid_post_url(value: Any) -> str:
    candidate = str(value or "").strip()
    if not candidate:
        return ""
    try:
        parsed = urlparse(candidate)
    except ValueError:
        return ""
    host = (parsed.hostname or "").casefold()
    if host != "facebook.com" and not host.endswith(".facebook.com"):
        return ""
    parts = [part for part in parsed.path.split("/") if part]
    if "posts" in parts or parsed.path.rstrip("/").endswith(
        ("story.php", "permalink.php")
    ):
        return candidate
    return ""

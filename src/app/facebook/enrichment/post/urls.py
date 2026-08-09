from __future__ import annotations

from typing import Any
from urllib.parse import parse_qs, urlencode, urlparse


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


def facebook_post_identity_from_url(url: str) -> tuple[str, str] | None:
    try:
        parsed = urlparse(url)
    except ValueError:
        return None
    host = (parsed.hostname or "").casefold()
    if host != "facebook.com" and not host.endswith(".facebook.com"):
        return None
    query = parse_qs(parsed.query)
    owner_id = (query.get("id") or [""])[0]
    post_id = (query.get("story_fbid") or [""])[0]
    if owner_id and post_id:
        return owner_id, post_id
    parts = [part for part in parsed.path.split("/") if part]
    if "posts" in parts:
        index = parts.index("posts")
        if index > 0 and index + 1 < len(parts):
            return parts[index - 1], parts[index + 1]
    return None


def normalized_facebook_post_url(url: str) -> str | None:
    """Return a stable direct URL while discarding Facebook tracking state."""
    identity = facebook_post_identity_from_url(url)
    if not identity:
        return None
    owner_id, post_id = identity
    parsed = urlparse(url)
    query = parse_qs(parsed.query)
    if query.get("story_fbid") and query.get("id"):
        return "https://m.facebook.com/story.php?" + urlencode(
            {"story_fbid": post_id, "id": owner_id}
        )
    return f"https://m.facebook.com/{owner_id}/posts/{post_id}"

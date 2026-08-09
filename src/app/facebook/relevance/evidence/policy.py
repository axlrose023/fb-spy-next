from __future__ import annotations

from collections.abc import Callable
from typing import Any
from urllib.parse import parse_qs, parse_qsl, urlencode, urlsplit, urlunsplit

from .models import EvidenceCandidate

_META_HOST_SUFFIXES = (
    "facebook.com",
    "facebook.net",
    "fbcdn.net",
    "instagram.com",
)
_PROFILE_TRACKING_PARAMS = {
    "fbclid",
    "fb_action_ids",
    "fb_action_types",
    "fb_source",
    "mibextid",
    "__tn__",
    "__cft__",
}


def isolated_external_url(
    value: Any,
    *,
    host_is_public: Callable[[str], bool],
) -> tuple[str, str]:
    """Return a public landing without profile tracking or Facebook l.php."""
    candidate = _external_landing_url(str(value or "").strip())
    if not candidate:
        return "", "missing_or_internal_passive_cta"
    try:
        parsed = urlsplit(candidate)
    except ValueError:
        return "", "invalid_passive_cta"
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        return "", "invalid_passive_cta"
    if parsed.username or parsed.password:
        return "", "credentialed_passive_cta_rejected"
    host = parsed.hostname.casefold().rstrip(".")
    if is_meta_host(host) or not host_is_public(host):
        return "", "unsafe_passive_cta_rejected"
    clean_query = urlencode(
        [
            (key, item)
            for key, item in parse_qsl(parsed.query, keep_blank_values=True)
            if key.casefold() not in _PROFILE_TRACKING_PARAMS
        ],
        doseq=True,
    )
    return (
        urlunsplit(
            (
                parsed.scheme,
                parsed.netloc,
                parsed.path or "/",
                clean_query,
                "",
            )
        ),
        "",
    )


def resolution_candidate(
    raw: dict[str, Any],
    *,
    host_is_public: Callable[[str], bool],
) -> EvidenceCandidate:
    target, issue = isolated_external_url(
        raw.get("cta_href"),
        host_is_public=host_is_public,
    )
    if target:
        return EvidenceCandidate("passive_cta_href", target)
    post_url = valid_facebook_post_url(raw.get("facebook_post_url"))
    if post_url:
        return EvidenceCandidate("anonymous_facebook_post", post_url)
    return EvidenceCandidate(issue=issue or "missing_isolated_resolution_handle")


def valid_facebook_post_url(value: Any) -> str:
    candidate = str(value or "").strip()
    if not candidate:
        return ""
    try:
        parsed = urlsplit(candidate)
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


def is_meta_host(host: str) -> bool:
    return any(
        host == suffix or host.endswith(f".{suffix}") for suffix in _META_HOST_SUFFIXES
    )


def summarize_isolated_resolutions(
    rows: list[dict[str, Any]],
    *,
    status: str,
    finished_at: str,
) -> dict[str, Any]:
    held = [row for row in rows if row.get("relevance_gate") == "hold"]
    results = [
        row["isolated_resolution"]
        for row in held
        if isinstance(row.get("isolated_resolution"), dict)
    ]
    resolved_statuses = {"completed", "reused_isolated_result"}
    resolved = [
        item
        for item in results
        if item.get("status") in resolved_statuses
        and bool(item.get("landing_resolved"))
        and bool(item.get("landing_screenshot_saved"))
    ]
    violations = sum(_isolation_violation(item) for item in results)
    return {
        "status": status,
        "finished_at": finished_at,
        "total": len(rows),
        "held": len(held),
        "resolved": len(resolved),
        "unresolved": len(results) - len(resolved),
        "external_navigations": _count(results, "external_navigation_started"),
        "anonymous_facebook_navigations": _count(
            results, "anonymous_facebook_navigation_started"
        ),
        "isolated_click_attempts": _count(results, "isolated_click_attempted"),
        "meta_requests_blocked": _total(results, "meta_requests_blocked"),
        "private_requests_blocked": _total(results, "private_requests_blocked"),
        "authenticated_profile_actions_started": _count(
            results, "active_profile_actions_started"
        ),
        "isolation_violations": violations,
    }


def _external_landing_url(value: str) -> str:
    if not value.startswith(("http://", "https://")):
        return ""
    try:
        parsed = urlsplit(value)
        host = (parsed.hostname or "").casefold()
        if not is_meta_host(host):
            return value
        if parsed.path.endswith("/l.php"):
            target = parse_qs(parsed.query).get("u", [""])[0]
            target_host = (urlsplit(target).hostname or "").casefold()
            if target.startswith(("http://", "https://")) and not is_meta_host(
                target_host
            ):
                return target
    except (TypeError, ValueError):
        return ""
    return ""


def _isolation_violation(item: dict[str, Any]) -> bool:
    return bool(item.get("isolated_navigation_started")) and (
        item.get("cookie_isolated") is not True
        or item.get("separate_browser_context") is not True
        or item.get("facebook_cookie_count_before") != 0
        or item.get("authenticated_profile_context") is not False
        or bool(item.get("active_profile_actions_started"))
    )


def _count(items: list[dict[str, Any]], key: str) -> int:
    return sum(bool(item.get(key)) for item in items)


def _total(items: list[dict[str, Any]], key: str) -> int:
    return sum(int(item.get(key) or 0) for item in items)

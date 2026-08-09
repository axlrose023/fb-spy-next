from __future__ import annotations

from typing import Any

from app.facebook.enrichment.landing.adapters.playwright import (
    neutralize_profile_pages,
)
from app.facebook.navigation import goto_with_retry
from app.services import facebook_runner

from ...models import EnrichmentOptions
from ...post import (
    is_facebook_url,
    matching_visible_feed_row,
    merge_passive_identity,
    resolve_facebook_post_url,
    valid_post_url,
)
from .mapping import ad_from_raw


def recover_allowed_post_url(
    context: Any,
    raw: dict[str, Any],
    *,
    options: EnrichmentOptions,
) -> tuple[str, dict[str, Any]]:
    recovery: dict[str, Any] = {
        "status": "pending",
        "profile_navigation_started": False,
        "matched_by": None,
        "media_guard": None,
        "error": None,
    }
    if raw.get("relevance_gate") != "allow":
        recovery["status"] = "blocked_by_relevance_gate"
        return "", recovery
    pages = list(getattr(context, "pages", []))
    page = next(
        (candidate for candidate in pages if candidate.url == "about:blank"),
        pages[0] if pages else None,
    )
    if page is None:
        recovery["status"] = "missing_profile_page"
        return "", recovery
    try:
        recovery["media_guard"] = facebook_runner.prepare_passive_media_guard(page)
        recovery["profile_navigation_started"] = True
        _restore_feed(page, options)
        element_id = str(raw.get("feed_element_id") or "")
        if element_id and page_has_feed_element(page, element_id):
            recovery["matched_by"] = "preserved_feed_element_id"
        else:
            observed = matching_visible_feed_row(
                page.evaluate(facebook_runner.DETECT_JS),
                raw,
            )
            if observed is None:
                recovery["status"] = "allowed_card_not_restored"
                return "", recovery
            element_id = str(observed.get("element_id") or "")
            recovery["matched_by"] = "strict_metadata"
            merge_passive_identity(raw, observed)
        return _resolve_permalink(page, raw, element_id, recovery)
    except Exception as exc:
        recovery["status"] = "failed"
        recovery["error"] = repr(exc)
        return "", recovery
    finally:
        neutralize_profile_pages(page, context)


def page_has_feed_element(page: Any, element_id: str) -> bool:
    try:
        return bool(
            page.evaluate(
                """
                elementId => Boolean(
                  document.querySelector(`[data-fbspy-id="${elementId}"]`)
                )
                """,
                element_id,
            )
        )
    except Exception:
        return False


def _restore_feed(page: Any, options: EnrichmentOptions) -> None:
    if page.url == "about:blank":
        page.go_back(
            wait_until="domcontentloaded",
            timeout=max(1, options.timeout_ms),
        )
    elif not is_facebook_url(page.url):
        goto_with_retry(
            page,
            "https://m.facebook.com/",
            timeout=max(1, options.timeout_ms),
            attempts=3,
        )
    facebook_runner.install_passive_media_guard(page)
    if options.wait_after_load > 0:
        page.wait_for_timeout(round(options.wait_after_load * 1000))


def _resolve_permalink(
    page: Any,
    raw: dict[str, Any],
    element_id: str,
    recovery: dict[str, Any],
) -> tuple[str, dict[str, Any]]:
    if not element_id:
        recovery["status"] = "missing_feed_element_id"
        return "", recovery
    ad = ad_from_raw(raw, element_id=element_id)
    if not resolve_facebook_post_url(
        page,
        ad,
        element_id,
        feed_url=page.url,
    ):
        recovery["status"] = "permalink_not_resolved"
        return "", recovery
    post_url = valid_post_url(ad.facebook_post_url)
    if not post_url:
        recovery["status"] = "invalid_recovered_post_url"
        return "", recovery
    raw.update(
        {
            "facebook_post_url": post_url,
            "facebook_page_url": ad.facebook_page_url,
            "fb_ad_id": ad.fb_ad_id,
        }
    )
    recovery.update({"status": "recovered", "post_url": post_url})
    return post_url, recovery

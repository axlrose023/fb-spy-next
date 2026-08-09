from __future__ import annotations

from dataclasses import asdict
from typing import Any, Literal

from app.browser import (
    BrowserOperationDeadlineExceeded,
    hard_deadline,
)
from app.facebook.enrichment import resolve_facebook_post_url, resolve_in_view

from ...artifacts import write_ads
from ...models import CandidateDecision
from .state import CollectionRunState

ResolutionOutcome = Literal["continue", "duplicate", "stop"]


def resolve_candidate_landing(
    page: Any,
    context: Any,
    row: dict[str, Any],
    decision: CandidateDecision,
    state: CollectionRunState,
    *,
    debug_id: int,
    now: float,
) -> ResolutionOutcome:
    options = state.options
    ad = decision.ad
    budget = max(30.0, options.landing_archive_timeout * 2 + 15.0)
    if not (
        options.resolve_landings
        and ad.ad_type == "link"
        and ad.displayed_domain
        and state.resolved < options.resolve_max
        and state.remaining_seconds(now) > budget
    ):
        return "continue"

    print(f"  resolving {ad.displayed_domain}", flush=True)
    state.cta_click_attempts += 1
    try:
        with hard_deadline(budget, f"landing resolve: {ad.displayed_domain}"):
            resolve_in_view(
                page,
                context,
                ad,
                row.get("btn"),
                row.get("element_id"),
                options.run_dir,
                debug=options.debug,
                debug_id=debug_id,
                feed_url=options.feed_url,
                archive_landing=options.archive_landings,
                landing_archive_timeout=options.landing_archive_timeout,
                landing_archive_max_resources=options.landing_archive_max_resources,
            )
    except BrowserOperationDeadlineExceeded as exc:
        state.resolve_timeouts += 1
        state.stop_reason = "resolve_timeout"
        print(
            f"  resolve timeout {ad.displayed_domain} after {budget:.0f}s; "
            "ending this cycle with the captured ad saved",
            flush=True,
        )
        if options.debug:
            options.debug.event(
                "resolve_hard_timeout",
                debug_id=debug_id,
                domain=ad.displayed_domain,
                timeout_seconds=budget,
                error=str(exc),
            )
        return "stop"

    if not ad.landing_full:
        return "continue"
    if not state.service.register_resolved(decision):
        state.duplicate_fb_ad_ids += 1
        if options.debug:
            options.debug.event(
                "duplicate_ad_id_skip",
                debug_id=debug_id,
                fb_ad_id=ad.fb_ad_id,
                domain=ad.displayed_domain,
            )
            options.debug.write_json(
                f"ads/{debug_id:04d}.json",
                {
                    "raw": row,
                    "parsed": asdict(ad),
                    "dedup_key": decision.key,
                    "skipped": "duplicate_fb_ad_id",
                },
            )
        print(
            f"  duplicate ad_id skipped {ad.displayed_domain} (ad_id={ad.fb_ad_id})",
            flush=True,
        )
        write_ads(options.run_dir / "ads.partial.json", state.ads)
        return "duplicate"

    state.resolved += 1
    print(
        f"  resolved {ad.displayed_domain} -> {ad.landing_clean} (ad_id={ad.fb_ad_id})",
        flush=True,
    )
    return "continue"


def resolve_candidate_permalink(
    page: Any,
    row: dict[str, Any],
    decision: CandidateDecision,
    state: CollectionRunState,
    *,
    debug_id: int,
    now: float,
) -> None:
    options = state.options
    ad = decision.ad
    if not (
        options.resolve_post_urls
        and not ad.facebook_post_url
        and row.get("element_id")
        and state.remaining_seconds(now) > 10
    ):
        return
    state.comment_open_attempts += 1
    resolved = resolve_facebook_post_url(
        page,
        ad,
        row.get("element_id"),
        feed_url=options.feed_url,
        debug=options.debug,
        debug_id=debug_id,
    )
    if resolved:
        print(f"  saved Facebook post {ad.facebook_post_url}", flush=True)

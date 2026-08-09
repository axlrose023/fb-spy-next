from __future__ import annotations

import time
from dataclasses import asdict
from typing import Any, Literal

from ...artifacts import write_ads
from ...models import CandidateDecision
from .candidate_media import record_candidate_video, save_candidate_screenshot
from .candidate_resolution import (
    resolve_candidate_landing,
    resolve_candidate_permalink,
)
from .state import CollectionRunState

CandidateOutcome = Literal["accepted", "skipped", "stop"]


def process_candidate(
    page: Any,
    context: Any,
    row: dict[str, Any],
    state: CollectionRunState,
) -> CandidateOutcome:
    options = state.options
    decision = state.service.consider_detection(row, country=options.country)
    ad = decision.ad
    creative_area = int(row.get("creative_area") or 0)
    if not decision.accepted:
        report_rejected_candidate(row, decision, state, creative_area=creative_area)
        return "skipped"

    for old_key in decision.removed_keys:
        if options.debug:
            options.debug.event(
                "lazy_media_replaced",
                old_key=old_key,
                new_key=decision.key,
                coarse_key=decision.coarse_key,
            )
    state.captured += 1
    debug_id = state.captured
    capture_candidate_dom(row, state, debug_id=debug_id)
    save_candidate_screenshot(
        page,
        row,
        state,
        ad,
        debug_id=debug_id,
        creative_area=creative_area,
    )
    state.service.accept(decision)
    if not record_candidate_video(page, row, state, ad, debug_id=debug_id):
        write_ads(options.run_dir / "ads.partial.json", state.ads)
        return "stop"

    # Persist before clicking: a broken landing must not lose the ad.
    write_ads(options.run_dir / "ads.partial.json", state.ads)
    resolution = resolve_candidate_landing(
        page,
        context,
        row,
        decision,
        state,
        debug_id=debug_id,
        now=time.time(),
    )
    if resolution == "stop":
        return "stop"
    if resolution == "duplicate":
        return "skipped"

    # Permalink recovery can replace the feed DOM, so it stays after CTA work.
    resolve_candidate_permalink(
        page,
        row,
        decision,
        state,
        debug_id=debug_id,
        now=time.time(),
    )
    if options.debug:
        options.debug.write_json(
            f"ads/{debug_id:04d}.json",
            {
                "raw": row,
                "parsed": asdict(ad),
                "dedup_key": decision.key,
            },
        )
    write_ads(options.run_dir / "ads.partial.json", state.ads)
    state.last_ad_scroll = state.scrolls
    return "accepted"


def report_rejected_candidate(
    row: dict[str, Any],
    decision: CandidateDecision,
    state: CollectionRunState,
    *,
    creative_area: int,
) -> None:
    debug = state.options.debug
    if not debug:
        return
    ad = decision.ad
    if decision.reason == "confirmed_duplicate":
        debug.event(
            "confirmed_duplicate_skip",
            scroll=state.scrolls,
            coarse_key=decision.coarse_key,
            advertiser=ad.advertiser,
            domain=ad.displayed_domain,
        )
    elif decision.reason == "exact_duplicate":
        debug.event(
            "dedup_skip",
            scroll=state.scrolls,
            dedup_key=decision.key,
            advertiser=ad.advertiser,
            domain=ad.displayed_domain,
            headline=ad.headline,
            creative_img=ad.creative_img,
        )
    elif decision.reason == "lazy_media_duplicate":
        debug.event(
            "lazy_media_duplicate_skip",
            scroll=state.scrolls,
            coarse_key=decision.coarse_key,
            existing_keys=list(decision.related_keys),
            advertiser=ad.advertiser,
            domain=ad.displayed_domain,
            headline=ad.headline,
            creative_img=ad.creative_img,
            creative_area=creative_area,
        )


def capture_candidate_dom(
    row: dict[str, Any],
    state: CollectionRunState,
    *,
    debug_id: int,
) -> None:
    debug = state.options.debug
    element_id = row.get("element_id")
    if not debug or not element_id:
        return
    try:
        html = state.feed_reader.card_html(element_id)
        debug.write_text(f"ads/{debug_id:04d}.html", html)
    except Exception as exc:
        debug.event(
            "ad_dom_failed",
            debug_id=debug_id,
            error=repr(exc),
            element_id=element_id,
        )

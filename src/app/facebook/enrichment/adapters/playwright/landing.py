from __future__ import annotations

from pathlib import Path
from typing import Any

from app.browser import hard_deadline
from app.facebook.collection import CollectedAd
from app.facebook.enrichment.landing.adapters.playwright import resolve_in_view

from ...models import EnrichmentOptions


def resolve_landing(
    page: Any,
    context: Any,
    ad: CollectedAd,
    element_id: str,
    *,
    post_url: str,
    sequence: int,
    run_dir: Path,
    options: EnrichmentOptions,
) -> None:
    timeout_seconds = max(30.0, options.landing_archive_timeout * 2 + 15.0)
    with hard_deadline(
        timeout_seconds,
        f"allowed landing enrichment: {ad.displayed_domain}",
    ):
        resolve_in_view(
            page,
            context,
            ad,
            None,
            element_id,
            run_dir,
            debug=None,
            debug_id=sequence,
            feed_url=post_url,
            archive_landing=True,
            landing_archive_timeout=options.landing_archive_timeout,
            landing_archive_max_resources=options.landing_archive_max_resources,
        )

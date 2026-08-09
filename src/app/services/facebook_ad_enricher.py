"""Compatibility CLI for the relevant-only Facebook enrichment module."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from app.facebook.enrichment.adapters.playwright.capture import (
    PlaywrightRelevantAdExecutor,
)
from app.facebook.enrichment.adapters.playwright.post import (
    recover_allowed_post_url,
)
from app.facebook.enrichment.commands import main
from app.facebook.enrichment.models import EnrichmentOptions
from app.facebook.enrichment.post import (
    matching_visible_feed_row,
    valid_post_url,
)
from app.facebook.enrichment.service import (
    EnrichmentService,
    denied_enrichment,
)
from app.services import facebook_runner


def _enrich_one(
    context: Any,
    raw: dict[str, Any],
    *,
    sequence: int,
    run_dir: Path,
    args: Any,
) -> tuple[dict[str, Any], dict[str, Any]]:
    if raw.get("relevance_gate") != "allow":
        result = denied_enrichment(raw)
        return result.ad, result.details
    service = EnrichmentService(clock=facebook_runner.utc_now)
    result = service.enrich_one(
        PlaywrightRelevantAdExecutor(EnrichmentOptions.from_namespace(args)),
        context,
        raw,
        sequence=sequence,
        run_dir=run_dir,
    )
    return result.ad, result.details


def _recover_allowed_post_url(
    context: Any,
    raw: dict[str, Any],
    *,
    args: Any,
) -> tuple[str, dict[str, Any]]:
    options = EnrichmentOptions(
        timeout_ms=getattr(args, "timeout_ms", 45_000),
        wait_after_load=getattr(args, "wait_after_load", 2.0),
    )
    return recover_allowed_post_url(context, raw, options=options)


def _matching_visible_feed_row(
    rows: Any,
    expected: dict[str, Any],
) -> dict[str, Any] | None:
    return matching_visible_feed_row(rows, expected)


def _valid_post_url(value: Any) -> str:
    return valid_post_url(value)


def _candidate_indexes(rows: list[dict[str, Any]]) -> list[int]:
    return [
        index for index, row in enumerate(rows) if row.get("relevance_gate") == "allow"
    ]


def _target_key(raw: dict[str, Any]) -> str:
    return EnrichmentService().target_key(raw)


def _summary(rows: list[dict[str, Any]], *, status: str) -> dict[str, Any]:
    return EnrichmentService(clock=facebook_runner.utc_now).summary(rows, status=status)


if __name__ == "__main__":
    raise SystemExit(main())

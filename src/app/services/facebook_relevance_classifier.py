"""Compatibility CLI for the modular Facebook relevance application."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from app.facebook.relevance.classification.input import analysis_input
from app.facebook.relevance.commands import main
from app.facebook.relevance.evidence.service import EvidenceService
from app.settings import get_config

_analysis_input = analysis_input


async def _finalize_ads(
    raw_ads: list[dict[str, Any]],
    run_dir: Path,
    relevance_filter: Any,
    *,
    include_video: bool,
) -> list[dict[str, Any]]:
    evidence = EvidenceService(
        relevance_filter,
        concurrency=get_config().facebook.relevance_filter_concurrency,
    )
    return await evidence.finalize_ads(
        raw_ads,
        run_dir,
        include_video=include_video,
    )


async def _resolve_held_ads(
    raw_ads: list[dict[str, Any]],
    run_dir: Path,
    relevance_filter: Any,
) -> list[dict[str, Any]]:
    evidence = EvidenceService(
        relevance_filter,
        concurrency=get_config().facebook.relevance_filter_concurrency,
    )
    return await evidence.resolve_held_ads(raw_ads, run_dir)


if __name__ == "__main__":
    raise SystemExit(main())

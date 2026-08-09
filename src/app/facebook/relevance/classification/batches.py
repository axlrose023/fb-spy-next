from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any

from ..service import RelevanceService
from .input import analysis_input


async def classify_ads(
    raw_ads: list[dict[str, Any]],
    run_dir: Path,
    relevance: RelevanceService,
    *,
    concurrency: int,
    include_video: bool,
    feed_only: bool = False,
) -> list[dict[str, Any]]:
    semaphore = asyncio.Semaphore(max(1, concurrency))

    async def classify_one(raw: dict[str, Any]) -> dict[str, Any]:
        decorated = dict(raw)
        try:
            async with semaphore:
                result = await relevance.analyze_raw_ad(
                    analysis_input(
                        raw,
                        include_video=include_video,
                        feed_only=feed_only,
                    ),
                    run_dir,
                    prefilter=feed_only,
                )
            decorated["relevance"] = result.summary
            decorated["relevance_source"] = result.source
        except Exception as exc:
            decorated["_relevance_error"] = repr(exc)
        return decorated

    return list(await asyncio.gather(*(classify_one(raw) for raw in raw_ads)))

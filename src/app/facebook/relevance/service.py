from __future__ import annotations

import asyncio
import logging
from pathlib import Path
from typing import Any

from .classification import RelevanceClassificationService
from .models import RelevanceResult

logger = logging.getLogger(__name__)


class RelevanceService:
    """Public application service for one ad or an ordered batch of ads."""

    def __init__(
        self,
        classifier: RelevanceClassificationService,
        *,
        concurrency: int = 3,
    ) -> None:
        self._classifier = classifier
        self.enabled = classifier.enabled
        self._concurrency = max(1, concurrency)

    async def analyze_raw_ad(
        self,
        raw: dict[str, Any],
        run_dir: Path,
        *,
        prefilter: bool = False,
    ) -> RelevanceResult:
        return await self._classifier.analyze(raw, run_dir, prefilter=prefilter)

    async def filter_raw_ads(
        self,
        raw_ads: list[dict[str, Any]],
        run_dir: Path,
    ) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
        if not self.enabled:
            return raw_ads, []
        semaphore = asyncio.Semaphore(self._concurrency)

        async def analyze_one(
            index: int,
            raw: dict[str, Any],
        ) -> tuple[int, dict[str, Any], RelevanceResult]:
            async with semaphore:
                result = await self.analyze_raw_ad(raw, run_dir)
                return index, raw, result

        results = await asyncio.gather(
            *(analyze_one(index, raw) for index, raw in enumerate(raw_ads, start=1))
        )
        accepted: list[dict[str, Any]] = []
        rejected: list[dict[str, Any]] = []
        for index, raw, result in sorted(results, key=lambda item: item[0]):
            decorated = dict(raw)
            decorated["relevance"] = result.summary
            decorated["relevance_source"] = result.source
            if result.relevant:
                accepted.append(decorated)
            else:
                rejected.append(decorated)
                logger.info(
                    "FB relevance rejected idx=%s advertiser=%r domain=%r reason=%s",
                    index,
                    raw.get("advertiser"),
                    raw.get("displayed_domain"),
                    result.summary.get("reason"),
                )
        return accepted, rejected

from __future__ import annotations

import asyncio
import json
import logging
import math
from pathlib import Path
from typing import Any
from uuid import uuid4

from app.settings import Config

logger = logging.getLogger("app.services.facebook.importer")

QueuedResult = tuple[int, dict[str, Any], Path]


class TaskiqRelevanceBatch:
    def __init__(self, config: Config) -> None:
        self._config = config

    async def filter(
        self,
        raw_ads: list[dict[str, Any]],
        run_dir: Path,
    ) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
        from app.tasks.facebook_relevance import analyze_facebook_ad_relevance

        batch_dir = run_dir / "relevance" / f"batch_{uuid4().hex}"
        batch_dir.mkdir(parents=True, exist_ok=True)
        queued = [
            (index, raw, batch_dir / f"{index:05d}.json")
            for index, raw in enumerate(raw_ads, start=1)
        ]
        concurrency = max(1, self._config.facebook.relevance_filter_concurrency)
        timeout_seconds = (
            self._config.facebook.relevance_filter_task_timeout_seconds
            * max(1, math.ceil(len(queued) / concurrency))
        )
        attempts = max(0, self._config.facebook.relevance_filter_task_retries) + 1
        for attempt in range(1, attempts + 1):
            missing = [item for item in queued if not item[2].exists()]
            if not missing:
                break
            for index, raw, result_path in missing:
                await analyze_facebook_ad_relevance.kiq(
                    raw,
                    str(run_dir),
                    index,
                    str(result_path),
                )
            logger.info(
                "Queued %s FB relevance tasks batch=%s attempt=%s/%s timeout_seconds=%.1f",
                len(missing),
                batch_dir.name,
                attempt,
                attempts,
                timeout_seconds,
            )
            completed = await self.wait_for_results(
                missing,
                timeout_seconds=timeout_seconds,
            )
            if completed == len(missing):
                break
            self._log_incomplete_batch(
                batch_dir.name,
                missing,
                completed,
                attempt,
                attempts,
            )
        return self._partition(queued)

    @staticmethod
    async def wait_for_results(
        queued: list[QueuedResult],
        timeout_seconds: float,
    ) -> int:
        deadline = asyncio.get_running_loop().time() + timeout_seconds
        while True:
            done = sum(1 for _, _, result_path in queued if result_path.exists())
            if done == len(queued) or asyncio.get_running_loop().time() >= deadline:
                return done
            await asyncio.sleep(0.5)

    @staticmethod
    def _log_incomplete_batch(
        batch_name: str,
        missing: list[QueuedResult],
        completed: int,
        attempt: int,
        attempts: int,
    ) -> None:
        if attempt < attempts:
            logger.warning(
                "FB relevance task batch retrying batch=%s done=%s total=%s attempt=%s/%s",
                batch_name,
                completed,
                len(missing),
                attempt,
                attempts,
            )
            return
        logger.warning(
            "FB relevance task batch timed out batch=%s done=%s total=%s attempts=%s missing=%s",
            batch_name,
            completed,
            len(missing),
            attempts,
            [index for index, _, path in missing if not path.exists()],
        )

    @staticmethod
    def _partition(
        queued: list[QueuedResult],
    ) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
        accepted: list[dict[str, Any]] = []
        rejected: list[dict[str, Any]] = []
        for index, raw, result_path in queued:
            decorated = dict(raw)
            if not result_path.exists():
                logger.warning(
                    "FB relevance task missing idx=%s advertiser=%r domain=%r",
                    index,
                    raw.get("advertiser"),
                    raw.get("displayed_domain"),
                )
                decorated["relevance"] = {
                    "result": "not_relevant",
                    "reason": "Relevance task timed out before writing a result.",
                }
                decorated["relevance_source"] = "taskiq_timeout"
                rejected.append(decorated)
                continue
            result = json.loads(result_path.read_text(encoding="utf-8"))
            summary = result.get("summary") or {}
            decorated["relevance"] = summary
            decorated["relevance_source"] = result.get("source") or "taskiq"
            if result.get("relevant") is True:
                accepted.append(decorated)
            else:
                rejected.append(decorated)
                logger.info(
                    "FB relevance rejected idx=%s advertiser=%r domain=%r reason=%s",
                    index,
                    raw.get("advertiser"),
                    raw.get("displayed_domain"),
                    summary.get("reason"),
                )
        return accepted, rejected

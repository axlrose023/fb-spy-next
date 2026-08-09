from __future__ import annotations

import asyncio
import hashlib
import json
import logging
from pathlib import Path
from typing import TYPE_CHECKING, Any
from uuid import UUID

from app.database.uow import UnitOfWork

from ..persistence import FacebookRun
from .models import QueuedRelevance, StreamingSyncState
from .stream_sync import sync_stream

if TYPE_CHECKING:
    from .service import FacebookAdsImporter

logger = logging.getLogger("app.services.facebook.importer")


class FacebookAdsStreamingImportSession:
    def __init__(
        self,
        importer: FacebookAdsImporter,
        run_id: UUID,
        run_dir: Path,
        ads_json_path: Path | None = None,
    ) -> None:
        self.importer = importer
        self.run_id = run_id
        self.run_dir = run_dir.expanduser().resolve()
        self.ads_json_path = (
            ads_json_path.expanduser().resolve()
            if ads_json_path
            else self.run_dir / "ads.json"
        )
        self.partial_json_path = self.run_dir / "ads.partial.json"
        self.unfiltered_path = self.run_dir / "ads.unfiltered.json"
        self.rejected_path = self.run_dir / "ads.rejected.json"
        self.batch_dir = self.run_dir / "relevance" / f"stream_{run_id.hex}"
        self.batch_dir.mkdir(parents=True, exist_ok=True)

        self._raw_ads: list[dict[str, Any]] = []
        self._source_order: list[str] = []
        self._source_indexes: dict[str, int] = {}
        self._queued: dict[str, QueuedRelevance] = {}
        self._accepted: dict[str, dict[str, Any]] = {}
        self._rejected: dict[str, dict[str, Any]] = {}
        self._inserted: set[str] = set()

    @property
    def pending_count(self) -> int:
        return sum(1 for item in self._queued.values() if not item.completed)

    async def poll(
        self,
        uow: UnitOfWork,
        run: FacebookRun,
        *,
        replace: bool = False,
    ) -> bool:
        changed = False
        raw_ads = self._read_source_ads()
        if raw_ads is not None:
            self._raw_ads = raw_ads
            changed = await self._discover(raw_ads) or changed
        changed = await self._collect_task_results() or changed
        changed = await self._retry_or_timeout_pending() or changed
        if changed or replace:
            await self._sync(uow, run, replace=replace)
        return changed

    async def finalize(self, uow: UnitOfWork, run: FacebookRun) -> None:
        await self.poll(uow, run)
        await self._sync(uow, run, replace=True)

    def expire_pending(self) -> None:
        for item in self._queued.values():
            if item.completed:
                continue
            self._complete(
                item,
                {
                    "index": item.index,
                    "relevant": False,
                    "summary": {
                        "result": "not_relevant",
                        "reason": "Relevance task timed out before final run sync.",
                    },
                    "source": "taskiq_timeout",
                    "raw_response": None,
                },
            )

    def _read_source_ads(self) -> list[dict[str, Any]] | None:
        for path in (self.partial_json_path, self.ads_json_path):
            if not path.exists():
                continue
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
            except json.JSONDecodeError:
                logger.debug("FB stream import skipped incomplete json path=%s", path)
                return None
            if not isinstance(data, list):
                logger.warning("FB stream import expected list path=%s", path)
                return None
            return [item for item in data if isinstance(item, dict)]
        return None

    async def _discover(self, raw_ads: list[dict[str, Any]]) -> bool:
        changed = False
        for index, raw in enumerate(raw_ads, start=1):
            source_key = self.importer._source_key(raw, index)
            if source_key not in self._source_order:
                self._source_order.append(source_key)
                self._source_indexes[source_key] = index
            if source_key in self._accepted or source_key in self._rejected:
                continue
            if source_key in self._queued:
                self._queued[source_key].raw = raw
                continue
            if not self.importer.relevance_filter.enabled:
                decorated = dict(raw)
                decorated["relevance_source"] = "disabled"
                self._accepted[source_key] = decorated
                changed = True
                continue
            item = QueuedRelevance(
                source_key=source_key,
                index=index,
                raw=raw,
                result_path=self._result_path(index, source_key),
            )
            if self.importer.config.facebook.relevance_filter_taskiq_enabled:
                self._queued[source_key] = item
                await self._queue_task(item)
            else:
                result = await self.importer.relevance_filter.analyze_raw_ad(
                    raw,
                    self.run_dir,
                )
                self._complete(
                    item,
                    {
                        "index": index,
                        "relevant": result.relevant,
                        "summary": result.summary,
                        "source": result.source,
                        "raw_response": result.raw_response,
                    },
                )
            changed = True
        return changed

    async def _queue_task(self, item: QueuedRelevance) -> None:
        from app.tasks.facebook_relevance import analyze_facebook_ad_relevance

        item.attempts += 1
        item.queued_at = asyncio.get_running_loop().time()
        await analyze_facebook_ad_relevance.kiq(
            item.raw,
            str(self.run_dir),
            item.index,
            str(item.result_path),
        )
        logger.info(
            "Queued FB stream relevance task idx=%s attempt=%s advertiser=%r domain=%r",
            item.index,
            item.attempts,
            item.raw.get("advertiser"),
            item.raw.get("displayed_domain"),
        )

    async def _collect_task_results(self) -> bool:
        changed = False
        for item in self._queued.values():
            if item.completed or not item.result_path.exists():
                continue
            self._complete(
                item,
                json.loads(item.result_path.read_text(encoding="utf-8")),
            )
            changed = True
        return changed

    async def _retry_or_timeout_pending(self) -> bool:
        if (
            not self.importer.relevance_filter.enabled
            or not self.importer.config.facebook.relevance_filter_taskiq_enabled
        ):
            return False
        now = asyncio.get_running_loop().time()
        timeout = self.importer.config.facebook.relevance_filter_task_timeout_seconds
        attempts = (
            max(0, self.importer.config.facebook.relevance_filter_task_retries) + 1
        )
        changed = False
        for item in self._queued.values():
            if item.completed or not item.queued_at or now - item.queued_at < timeout:
                continue
            if item.attempts < attempts:
                logger.warning(
                    "Retrying FB stream relevance task idx=%s attempt=%s/%s",
                    item.index,
                    item.attempts + 1,
                    attempts,
                )
                await self._queue_task(item)
                continue
            self._complete(
                item,
                {
                    "index": item.index,
                    "relevant": False,
                    "summary": {
                        "result": "not_relevant",
                        "reason": "Relevance task timed out before writing a result.",
                    },
                    "source": "taskiq_timeout",
                    "raw_response": None,
                },
            )
            changed = True
        return changed

    def _complete(self, item: QueuedRelevance, result: dict[str, Any]) -> None:
        decorated = dict(item.raw)
        summary = result.get("summary") or {}
        decorated["relevance"] = summary
        decorated["relevance_source"] = result.get("source") or "taskiq"
        item.completed = True
        if result.get("relevant") is True:
            self._accepted[item.source_key] = decorated
            return
        self._rejected[item.source_key] = decorated
        logger.info(
            "FB stream relevance rejected idx=%s advertiser=%r domain=%r reason=%s",
            item.index,
            item.raw.get("advertiser"),
            item.raw.get("displayed_domain"),
            summary.get("reason"),
        )

    async def _sync(
        self,
        uow: UnitOfWork,
        run: FacebookRun,
        *,
        replace: bool,
    ) -> None:
        await sync_stream(
            self.importer,
            uow,
            run,
            StreamingSyncState(
                raw_ads=self._raw_ads,
                source_order=self._source_order,
                source_indexes=self._source_indexes,
                accepted=self._accepted,
                rejected=self._rejected,
                inserted=self._inserted,
            ),
            run_dir=self.run_dir,
            ads_json_path=self.ads_json_path,
            unfiltered_path=self.unfiltered_path,
            rejected_path=self.rejected_path,
            replace=replace,
        )

    def _result_path(self, index: int, source_key: str) -> Path:
        digest = hashlib.sha1(source_key.encode("utf-8")).hexdigest()[:12]
        return self.batch_dir / f"{index:05d}_{digest}.json"

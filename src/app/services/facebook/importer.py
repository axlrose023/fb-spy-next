from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import math
from datetime import datetime
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

from app.ad_library.ads import (
    Ad,
    AdIngestionRequest,
    AdIngestionService,
    AdMapper,
    AdMappingPolicy,
    AdSource,
)
from app.ad_library.ads.adapters.persistence import SqlAlchemyAdRepository
from app.ad_library.ads.ingestion.deduplication import explicitly_relevant
from app.ad_library.ads.ingestion.mapping import (
    clean_value,
    parse_datetime,
    source_key,
)
from app.ad_library.media import MediaStorage
from app.ad_library.media.configuration import configured_storage
from app.database.uow import UnitOfWork
from app.facebook.relevance import configured_relevance_service
from app.facebook.runs.adapters.persistence import FacebookRun
from app.settings import Config

logger = logging.getLogger(__name__)


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
        self._queued: dict[str, _QueuedRelevance] = {}
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
            payload = {
                "index": item.index,
                "relevant": False,
                "summary": {
                    "result": "not_relevant",
                    "reason": "Relevance task timed out before final run sync.",
                },
                "source": "taskiq_timeout",
                "raw_response": None,
            }
            self._complete(item, payload)

    def _read_source_ads(self) -> list[dict[str, Any]] | None:
        candidates = [self.partial_json_path, self.ads_json_path]

        for path in candidates:
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
            if self.importer.config.facebook.relevance_filter_taskiq_enabled:
                result_path = self._result_path(index, source_key)
                item = _QueuedRelevance(
                    source_key=source_key,
                    index=index,
                    raw=raw,
                    result_path=result_path,
                )
                self._queued[source_key] = item
                await self._queue_task(item)
                changed = True
            else:
                result = await self.importer.relevance_filter.analyze_raw_ad(
                    raw,
                    self.run_dir,
                )
                payload = {
                    "index": index,
                    "relevant": result.relevant,
                    "summary": result.summary,
                    "source": result.source,
                    "raw_response": result.raw_response,
                }
                item = _QueuedRelevance(
                    source_key=source_key,
                    index=index,
                    raw=raw,
                    result_path=self._result_path(index, source_key),
                )
                self._complete(item, payload)
                changed = True
        return changed

    async def _queue_task(self, item: _QueuedRelevance) -> None:
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
            result = json.loads(item.result_path.read_text(encoding="utf-8"))
            self._complete(item, result)
            changed = True
        return changed

    async def _retry_or_timeout_pending(self) -> bool:
        if (
            not self.importer.relevance_filter.enabled
            or not self.importer.config.facebook.relevance_filter_taskiq_enabled
        ):
            return False
        now = asyncio.get_running_loop().time()
        timeout_seconds = (
            self.importer.config.facebook.relevance_filter_task_timeout_seconds
        )
        max_attempts = (
            max(0, self.importer.config.facebook.relevance_filter_task_retries) + 1
        )
        changed = False
        for item in self._queued.values():
            if item.completed or not item.queued_at:
                continue
            if now - item.queued_at < timeout_seconds:
                continue
            if item.attempts < max_attempts:
                logger.warning(
                    "Retrying FB stream relevance task idx=%s attempt=%s/%s",
                    item.index,
                    item.attempts + 1,
                    max_attempts,
                )
                await self._queue_task(item)
                continue
            payload = {
                "index": item.index,
                "relevant": False,
                "summary": {
                    "result": "not_relevant",
                    "reason": "Relevance task timed out before writing a result.",
                },
                "source": "taskiq_timeout",
                "raw_response": None,
            }
            self._complete(item, payload)
            changed = True
        return changed

    def _complete(self, item: _QueuedRelevance, result: dict[str, Any]) -> None:
        decorated = dict(item.raw)
        summary = result.get("summary") or {}
        decorated["relevance"] = summary
        decorated["relevance_source"] = result.get("source") or "taskiq"
        item.completed = True
        if result.get("relevant") is True:
            self._accepted[item.source_key] = decorated
        else:
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
        self.importer.apply_run_metadata(run, self.run_dir)
        accepted = self._ordered(self._accepted)
        rejected = self._ordered(self._rejected)
        self.importer._write_json_atomic(self.unfiltered_path, self._raw_ads)
        self.importer._write_json_atomic(self.ads_json_path, accepted)
        self.importer._write_json_atomic(self.rejected_path, rejected)

        if replace:
            self._inserted.clear()
            keys_to_insert = [
                key for key in self._source_order if key in self._accepted
            ]
        else:
            keys_to_insert = [
                key
                for key in self._source_order
                if key in self._accepted and key not in self._inserted
            ]

        sources = [
            AdSource(
                token=key,
                index=self._source_indexes[key],
                raw=self._accepted[key],
            )
            for key in keys_to_insert
        ]
        result = await self.importer.ingestion_service(uow).ingest(
            AdIngestionRequest(
                run_id=run.id,
                run_dir=self.run_dir,
                sources=sources,
                country_fallback=run.profile_country,
                replace_existing=replace,
                upload_media=replace,
            )
        )
        self.importer.log_skipped_ads(result.skipped_count)
        if result.inserted:
            self._inserted.update(keys_to_insert)

        if replace:
            stats_ads = result.observed
        else:
            stats_sources = [
                AdSource(
                    token=key,
                    index=self._source_indexes[key],
                    raw=self._accepted[key],
                )
                for key in self._source_order
                if key in self._accepted
            ]
            mapped_stats = await asyncio.to_thread(
                self.importer.ad_mapper.map_sources,
                run.id,
                stats_sources,
                self.run_dir,
                run.profile_country,
            )
            stats_ads = [ad for _, ad in mapped_stats]
        self.importer._apply_run_stats(
            run,
            run_dir=self.run_dir,
            ads_json_path=self.ads_json_path,
            ads=stats_ads,
        )
        await uow.flush()

    def _ordered(self, mapping: dict[str, dict[str, Any]]) -> list[dict[str, Any]]:
        return [mapping[key] for key in self._source_order if key in mapping]

    def _result_path(self, index: int, source_key: str) -> Path:
        digest = hashlib.sha1(source_key.encode("utf-8")).hexdigest()[:12]
        return self.batch_dir / f"{index:05d}_{digest}.json"


class _QueuedRelevance:
    def __init__(
        self,
        *,
        source_key: str,
        index: int,
        raw: dict[str, Any],
        result_path: Path,
    ) -> None:
        self.source_key = source_key
        self.index = index
        self.raw = raw
        self.result_path = result_path
        self.attempts = 0
        self.queued_at = 0.0
        self.completed = False


class FacebookAdsImporter:
    def __init__(self, config: Config, media_storage: MediaStorage | None = None):
        self.config = config
        self.relevance_filter = configured_relevance_service(config)
        self.media_storage = media_storage or configured_storage(config)
        self.ad_mapper = AdMapper(
            AdMappingPolicy(
                data_dir=config.facebook.data_dir,
                default_country=config.facebook.default_country,
            )
        )

    def ingestion_service(self, uow: UnitOfWork) -> AdIngestionService:
        return AdIngestionService(
            SqlAlchemyAdRepository(uow.session),
            self.media_storage,
            self.ad_mapper,
        )

    def create_streaming_session(
        self,
        run_id: UUID,
        run_dir: Path,
        ads_json_path: Path | None = None,
    ) -> FacebookAdsStreamingImportSession:
        return FacebookAdsStreamingImportSession(
            self,
            run_id,
            run_dir,
            ads_json_path=ads_json_path,
        )

    def apply_run_metadata(self, run: FacebookRun, run_dir: Path) -> None:
        meta = self._load_run_meta(run_dir)
        if not meta:
            return
        run.octo_profile_uuid = (
            self._clean_meta_value(meta.get("octo_profile_uuid"))
            or run.octo_profile_uuid
        )
        run.profile_country = (
            self._clean_meta_value(meta.get("profile_country")) or run.profile_country
        )
        run.octo_ip = self._clean_meta_value(meta.get("octo_ip")) or run.octo_ip

    async def import_ads_json(
        self,
        uow: UnitOfWork,
        run: FacebookRun,
        ads_json_path: Path,
        apply_relevance: bool = True,
    ) -> FacebookRun:
        ads_json_path = ads_json_path.expanduser().resolve()
        run_dir = ads_json_path.parent
        self.apply_run_metadata(run, run_dir)
        source_json_path = ads_json_path
        unfiltered_path = run_dir / "ads.unfiltered.json"
        if (
            apply_relevance
            and self.relevance_filter.enabled
            and unfiltered_path.exists()
        ):
            source_json_path = unfiltered_path
        raw_ads = json.loads(source_json_path.read_text(encoding="utf-8"))
        raw_total = len(raw_ads)

        if apply_relevance:
            if (
                self.relevance_filter.enabled
                and self.config.facebook.relevance_filter_taskiq_enabled
            ):
                raw_ads, rejected_ads = await self._filter_with_taskiq(raw_ads, run_dir)
            else:
                raw_ads, rejected_ads = await self.relevance_filter.filter_raw_ads(
                    raw_ads,
                    run_dir,
                )
        else:
            rejected_ads = []
        if apply_relevance and self.relevance_filter.enabled:
            self._write_filter_outputs(ads_json_path, raw_ads, rejected_ads, raw_total)

        sources = [
            AdSource(token=str(index), index=index, raw=raw)
            for index, raw in enumerate(raw_ads, start=1)
        ]
        result = await self.ingestion_service(uow).ingest(
            AdIngestionRequest(
                run_id=run.id,
                run_dir=run_dir,
                sources=sources,
                country_fallback=run.profile_country,
                replace_existing=True,
                upload_media=True,
            )
        )
        self.log_skipped_ads(result.skipped_count)

        self._apply_run_stats(
            run,
            run_dir=run_dir,
            ads_json_path=ads_json_path,
            ads=result.observed,
        )
        await uow.flush()
        return run

    async def _filter_with_taskiq(
        self,
        raw_ads: list[dict[str, Any]],
        run_dir: Path,
    ) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
        from app.tasks.facebook_relevance import analyze_facebook_ad_relevance

        batch_dir = run_dir / "relevance" / f"batch_{uuid4().hex}"
        batch_dir.mkdir(parents=True, exist_ok=True)
        queued: list[tuple[int, dict[str, Any], Path]] = []
        for index, raw in enumerate(raw_ads, start=1):
            result_path = batch_dir / f"{index:05d}.json"
            queued.append((index, raw, result_path))

        concurrency = max(1, self.config.facebook.relevance_filter_concurrency)
        timeout_seconds = (
            self.config.facebook.relevance_filter_task_timeout_seconds
            * max(1, math.ceil(len(queued) / concurrency))
        )
        attempts = max(0, self.config.facebook.relevance_filter_task_retries) + 1
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

            completed = await self._wait_for_taskiq_results(
                missing,
                timeout_seconds=timeout_seconds,
            )
            if completed == len(missing):
                break
            if attempt < attempts:
                logger.warning(
                    "FB relevance task batch retrying batch=%s done=%s total=%s attempt=%s/%s",
                    batch_dir.name,
                    completed,
                    len(missing),
                    attempt,
                    attempts,
                )
            else:
                logger.warning(
                    "FB relevance task batch timed out batch=%s done=%s total=%s attempts=%s missing=%s",
                    batch_dir.name,
                    completed,
                    len(missing),
                    attempts,
                    [index for index, _, path in missing if not path.exists()],
                )

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

    async def _wait_for_taskiq_results(
        self,
        queued: list[tuple[int, dict[str, Any], Path]],
        timeout_seconds: float,
    ) -> int:
        deadline = asyncio.get_running_loop().time() + timeout_seconds
        while True:
            done = sum(1 for _, _, result_path in queued if result_path.exists())
            if done == len(queued) or asyncio.get_running_loop().time() >= deadline:
                return done
            await asyncio.sleep(0.5)

    @staticmethod
    def raw_ads_explicitly_relevant(raw_ads: list[dict[str, Any]]) -> bool:
        return explicitly_relevant(
            [
                AdSource(token=str(index), index=index, raw=raw)
                for index, raw in enumerate(raw_ads, start=1)
            ]
        )

    @staticmethod
    def log_skipped_ads(skipped_count: int) -> None:
        if skipped_count:
            logger.info("Skipped %s already imported Facebook ad(s)", skipped_count)

    @staticmethod
    def _write_filter_outputs(
        ads_json_path: Path,
        accepted: list[dict[str, Any]],
        rejected: list[dict[str, Any]],
        raw_total: int,
    ) -> None:
        if raw_total and not (ads_json_path.parent / "ads.unfiltered.json").exists():
            ads_json_path.replace(ads_json_path.parent / "ads.unfiltered.json")
        FacebookAdsImporter._write_json_atomic(ads_json_path, accepted)
        FacebookAdsImporter._write_json_atomic(
            ads_json_path.parent / "ads.rejected.json",
            rejected,
        )

    @staticmethod
    def _write_json_atomic(path: Path, payload: Any) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(path.suffix + ".tmp")
        tmp.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        tmp.replace(path)

    def _apply_run_stats(
        self,
        run: FacebookRun,
        *,
        run_dir: Path,
        ads_json_path: Path,
        ads: list[Ad],
    ) -> None:
        run.ads_json_path = str(ads_json_path)
        run.runner_run_dir = str(run_dir)
        run.debug_dir = str(run_dir / "debug") if (run_dir / "debug").exists() else None
        run.total_ads = len(ads)
        run.link_ads = sum(1 for ad in ads if ad.ad_type == "link")
        run.resolved_ads = sum(1 for ad in ads if ad.landing_full)
        run.video_ads = sum(1 for ad in ads if ad.has_video or ad.ad_type == "video")
        run.bad_screenshots = sum(1 for ad in ads if ad.screenshot_ok is False)

    def _build_ad(
        self,
        run_id: UUID,
        source_index: int,
        raw: dict[str, Any],
        run_dir: Path,
        *,
        country_fallback: str | None = None,
    ) -> Ad:
        return self.ad_mapper.map(
            run_id,
            source_index,
            raw,
            run_dir,
            country_fallback=country_fallback,
        )

    def _runner_media_path(self, run_dir: Path, value: str | None) -> str:
        return self.ad_mapper.media_path(run_dir, value)

    @staticmethod
    def _load_run_meta(run_dir: Path) -> dict[str, Any]:
        path = run_dir / "run_meta.json"
        if not path.exists():
            return {}
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            logger.warning("Failed to read FB run metadata path=%s", path)
            return {}
        if not isinstance(data, dict):
            logger.warning("FB run metadata expected object path=%s", path)
            return {}
        return data

    @staticmethod
    def _clean_meta_value(value: Any) -> str | None:
        return clean_value(value)

    @staticmethod
    def _source_key(raw: dict[str, Any], source_index: int) -> str:
        return source_key(raw, source_index)

    @staticmethod
    def _parse_datetime(value: str | None) -> datetime | None:
        return parse_datetime(value)

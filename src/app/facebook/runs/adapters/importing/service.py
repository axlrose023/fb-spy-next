from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any, cast
from uuid import UUID

from app.ad_library import configured_storage
from app.ad_library.ads import (
    Ad,
    AdIngestionRequest,
    AdIngestionService,
    AdMapper,
    AdMappingPolicy,
    AdSource,
    clean_value,
    explicitly_relevant,
    parse_datetime,
    source_key,
)
from app.ad_library.media import MediaStorage
from app.database.uow import UnitOfWork
from app.facebook.relevance import configured_relevance_service
from app.settings import Config

from ..persistence import FacebookRun
from .artifacts import (
    apply_run_stats,
    load_run_meta,
    write_filter_outputs,
    write_json_atomic,
)
from .relevance_batch import QueuedResult, TaskiqRelevanceBatch
from .streaming import FacebookAdsStreamingImportSession

logger = logging.getLogger("app.services.facebook.importer")


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
            uow.facebook_ads,
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
        raw_ads = self._read_ads(source_json_path)
        raw_total = len(raw_ads)

        rejected_ads: list[dict[str, Any]] = []
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
        if apply_relevance and self.relevance_filter.enabled:
            self._write_filter_outputs(ads_json_path, raw_ads, rejected_ads, raw_total)

        result = await self.ingestion_service(uow).ingest(
            AdIngestionRequest(
                run_id=run.id,
                run_dir=run_dir,
                sources=[
                    AdSource(token=str(index), index=index, raw=raw)
                    for index, raw in enumerate(raw_ads, start=1)
                ],
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
        return await TaskiqRelevanceBatch(self.config).filter(raw_ads, run_dir)

    async def _wait_for_taskiq_results(
        self,
        queued: list[QueuedResult],
        timeout_seconds: float,
    ) -> int:
        return await TaskiqRelevanceBatch.wait_for_results(queued, timeout_seconds)

    @staticmethod
    def raw_ads_explicitly_relevant(raw_ads: list[dict[str, Any]]) -> bool:
        return cast(
            bool,
            explicitly_relevant(
                [
                    AdSource(token=str(index), index=index, raw=raw)
                    for index, raw in enumerate(raw_ads, start=1)
                ]
            ),
        )

    @staticmethod
    def log_skipped_ads(skipped_count: int) -> None:
        if skipped_count:
            logger.info("Skipped %s already imported Facebook ad(s)", skipped_count)

    _write_filter_outputs = staticmethod(write_filter_outputs)
    _write_json_atomic = staticmethod(write_json_atomic)

    def _apply_run_stats(
        self,
        run: FacebookRun,
        *,
        run_dir: Path,
        ads_json_path: Path,
        ads: list[Ad],
    ) -> None:
        apply_run_stats(
            run,
            run_dir=run_dir,
            ads_json_path=ads_json_path,
            ads=ads,
        )

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
        return cast(str, self.ad_mapper.media_path(run_dir, value))

    _load_run_meta = staticmethod(load_run_meta)
    _clean_meta_value = staticmethod(clean_value)
    _source_key = staticmethod(source_key)
    _parse_datetime = staticmethod(parse_datetime)

    @staticmethod
    def _read_ads(path: Path) -> list[dict[str, Any]]:
        return cast(
            list[dict[str, Any]],
            json.loads(path.read_text(encoding="utf-8")),
        )

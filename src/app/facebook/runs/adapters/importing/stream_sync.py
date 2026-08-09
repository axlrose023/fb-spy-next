from __future__ import annotations

import asyncio
from pathlib import Path
from typing import TYPE_CHECKING

from app.ad_library.ads import AdIngestionRequest, AdSource
from app.database.uow import UnitOfWork

from ..persistence import FacebookRun
from .artifacts import write_json_atomic
from .models import StreamingSyncState

if TYPE_CHECKING:
    from .service import FacebookAdsImporter


async def sync_stream(
    importer: FacebookAdsImporter,
    uow: UnitOfWork,
    run: FacebookRun,
    state: StreamingSyncState,
    *,
    run_dir: Path,
    ads_json_path: Path,
    unfiltered_path: Path,
    rejected_path: Path,
    replace: bool,
) -> None:
    importer.apply_run_metadata(run, run_dir)
    accepted = _ordered(state.source_order, state.accepted)
    rejected = _ordered(state.source_order, state.rejected)
    write_json_atomic(unfiltered_path, state.raw_ads)
    write_json_atomic(ads_json_path, accepted)
    write_json_atomic(rejected_path, rejected)

    if replace:
        state.inserted.clear()
        keys_to_insert = [key for key in state.source_order if key in state.accepted]
    else:
        keys_to_insert = [
            key
            for key in state.source_order
            if key in state.accepted and key not in state.inserted
        ]

    sources = [
        AdSource(
            token=key,
            index=state.source_indexes[key],
            raw=state.accepted[key],
        )
        for key in keys_to_insert
    ]
    result = await importer.ingestion_service(uow).ingest(
        AdIngestionRequest(
            run_id=run.id,
            run_dir=run_dir,
            sources=sources,
            country_fallback=run.profile_country,
            replace_existing=replace,
            upload_media=replace,
        )
    )
    importer.log_skipped_ads(result.skipped_count)
    if result.inserted:
        state.inserted.update(keys_to_insert)

    if replace:
        stats_ads = result.observed
    else:
        stats_sources = [
            AdSource(
                token=key,
                index=state.source_indexes[key],
                raw=state.accepted[key],
            )
            for key in state.source_order
            if key in state.accepted
        ]
        mapped_stats = await asyncio.to_thread(
            importer.ad_mapper.map_sources,
            run.id,
            stats_sources,
            run_dir,
            run.profile_country,
        )
        stats_ads = [ad for _, ad in mapped_stats]
    importer._apply_run_stats(
        run,
        run_dir=run_dir,
        ads_json_path=ads_json_path,
        ads=stats_ads,
    )
    await uow.flush()


def _ordered(
    source_order: list[str],
    mapping: dict[str, dict],
) -> list[dict]:
    return [mapping[key] for key in source_order if key in mapping]

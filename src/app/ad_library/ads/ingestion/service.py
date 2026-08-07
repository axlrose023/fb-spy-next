from __future__ import annotations

import asyncio

from ..contracts import AdIngestionRepository, AdMediaUploader
from .deduplication import ad_identity, explicitly_relevant, new_sources
from .mapping import AdMapper
from .models import AdIngestionRequest, AdIngestionResult


class AdIngestionService:
    def __init__(
        self,
        ads: AdIngestionRepository,
        media: AdMediaUploader,
        mapper: AdMapper,
    ) -> None:
        self._ads = ads
        self._media = media
        self._mapper = mapper

    async def ingest(self, request: AdIngestionRequest) -> AdIngestionResult:
        if request.replace_existing:
            await self._ads.delete_run_ads(request.run_id)
        mapped = await asyncio.to_thread(
            self._mapper.map_sources,
            request.run_id,
            request.sources,
            request.run_dir,
            request.country_fallback,
        )
        identities = {
            identity
            for _, ad in mapped
            if (identity := ad_identity(ad)) is not None
        }
        existing = await self._ads.existing_identities(identities)
        selected = new_sources(mapped, existing)
        inserted = [ad for _, ad in selected]
        if request.upload_media and inserted:
            await self._media.upload_ads(
                inserted,
                relevance_verified=explicitly_relevant(
                    [source for source, _ in selected]
                ),
            )
        await self._ads.add_many(inserted)
        return AdIngestionResult(
            observed=[ad for _, ad in mapped],
            inserted=inserted,
            inserted_tokens=frozenset(source.token for source, _ in selected),
            skipped_count=len(mapped) - len(selected),
        )

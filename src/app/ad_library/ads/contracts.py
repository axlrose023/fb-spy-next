from __future__ import annotations

from collections.abc import Sequence
from typing import Protocol
from uuid import UUID

from app.ad_library.media import MediaKind

from .models import Ad, AdPage, AdQuery


class AdReader(Protocol):
    async def get(self, ad_id: UUID) -> Ad | None: ...


class AdCatalogRepository(AdReader, Protocol):
    async def page(self, query: AdQuery) -> AdPage: ...


class MediaLinkBuilder(Protocol):
    def url_for(
        self,
        ad_id: UUID,
        kind: MediaKind,
        stored_reference: str | None,
        *,
        now: int | None = None,
    ) -> str | None: ...


class AdIngestionRepository(Protocol):
    async def existing_identities(
        self,
        identities: set[tuple[str, str]],
    ) -> set[tuple[str, str]]: ...

    async def add_many(self, ads: Sequence[Ad]) -> None: ...

    async def delete_run_ads(self, run_id: UUID) -> None: ...


class AdMediaUploader(Protocol):
    async def upload_ads(
        self,
        ads: Sequence[Ad],
        *,
        relevance_verified: bool,
    ) -> int: ...

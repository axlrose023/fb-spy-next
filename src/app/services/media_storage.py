from __future__ import annotations

from typing import TYPE_CHECKING, Any
from uuid import UUID

from app.ad_library.media import (
    MEDIA_SPECS,
    MediaKind,
    MediaNotFoundError,
    MediaPayload,
    MediaRangeError,
    MediaStorageError,
    MediaTokenError,
)
from app.ad_library.media.configuration import configured_signer, configured_storage
from app.ad_library.media.paths.object_keys import (
    S3_REFERENCE_PREFIX,
    is_s3_reference,
)
from app.ad_library.media.streaming import iter_media_body
from app.settings import Config

if TYPE_CHECKING:
    from app.api.modules.ads.models import FacebookAd


class MediaURLSigner:
    """Deprecated constructor-compatible facade for the media signer."""

    def __init__(self, config: Config) -> None:
        self._signer = configured_signer(config)

    @property
    def ttl_seconds(self) -> int:
        return self._signer.ttl_seconds

    def url_for(
        self,
        ad_id: UUID,
        kind: MediaKind,
        stored_reference: str | None,
        *,
        now: int | None = None,
    ) -> str | None:
        return self._signer.url_for(
            ad_id,
            kind,
            stored_reference,
            now=now,
        )

    def create_token(
        self,
        ad_id: UUID,
        kind: MediaKind,
        *,
        now: int | None = None,
    ) -> str:
        return self._signer.create_token(ad_id, kind, now=now)

    def verify_token(
        self,
        token: str,
        ad_id: UUID,
        kind: MediaKind,
        *,
        now: int | None = None,
    ) -> int:
        return self._signer.verify_token(token, ad_id, kind, now=now)


class MediaStorage:
    """Deprecated constructor-compatible facade for configured media storage."""

    def __init__(
        self,
        config: Config,
        *,
        s3_client: Any | None = None,
        s3_read_client: Any | None = None,
    ) -> None:
        self._storage = configured_storage(
            config,
            s3_client=s3_client,
            s3_read_client=s3_read_client,
        )

    @property
    def backend(self) -> str:
        return self._storage.backend

    async def upload_ads(
        self,
        ads: list[FacebookAd],
        *,
        relevance_verified: bool,
    ) -> int:
        return await self._storage.upload_ads(
            ads,
            relevance_verified=relevance_verified,
        )

    async def open(
        self,
        stored_reference: str,
        kind: MediaKind,
        *,
        ad_id: UUID,
        range_header: str | None = None,
    ) -> MediaPayload:
        return await self._storage.open(
            stored_reference,
            kind,
            ad_id=ad_id,
            range_header=range_header,
        )

    async def head(
        self,
        stored_reference: str,
        kind: MediaKind,
        *,
        ad_id: UUID,
    ) -> MediaPayload:
        return await self._storage.head(stored_reference, kind, ad_id=ad_id)

    async def delete_object(self, stored_reference: str) -> None:
        await self._storage.delete_object(stored_reference)


__all__ = [
    "MEDIA_SPECS",
    "S3_REFERENCE_PREFIX",
    "MediaKind",
    "MediaNotFoundError",
    "MediaPayload",
    "MediaRangeError",
    "MediaStorage",
    "MediaStorageError",
    "MediaTokenError",
    "MediaURLSigner",
    "is_s3_reference",
    "iter_media_body",
]

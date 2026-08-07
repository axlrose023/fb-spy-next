from __future__ import annotations

import asyncio
from collections.abc import Sequence
from uuid import UUID

from .contracts import (
    AdMediaOwner,
    AdMediaReferenceReader,
    LocalMediaGateway,
    MediaAccess,
    MediaLinkSigner,
    RemoteMediaGateway,
)
from .exceptions import MediaNotFoundError, MediaStorageError
from .models import MEDIA_SPECS, MediaKind, MediaPayload
from .paths.object_keys import is_s3_reference
from .ranges import validate_range_syntax


class MediaStorage:
    def __init__(
        self,
        local: LocalMediaGateway,
        remote: RemoteMediaGateway | None,
        *,
        backend: str,
        upload_concurrency: int,
    ) -> None:
        self._local = local
        self._remote = remote
        self._backend = backend
        self._upload_concurrency = upload_concurrency

    @property
    def backend(self) -> str:
        return self._backend

    async def upload_ads(
        self,
        ads: Sequence[AdMediaOwner],
        *,
        relevance_verified: bool,
    ) -> int:
        if self._backend != "s3" or not ads:
            return 0
        if not relevance_verified:
            raise MediaStorageError(
                "refusing to upload media without explicit relevance verification"
            )
        remote = self._require_remote()
        semaphore = asyncio.Semaphore(self._upload_concurrency)
        pending: list[tuple[AdMediaOwner, MediaKind, str]] = []
        for ad in ads:
            for kind, spec in MEDIA_SPECS.items():
                reference = getattr(ad, spec.model_attribute)
                if reference and not is_s3_reference(reference):
                    pending.append((ad, kind, reference))

        async def upload_one(
            ad: AdMediaOwner,
            kind: MediaKind,
            reference: str,
        ) -> tuple[AdMediaOwner, MediaKind, str]:
            async with semaphore:
                marker = await remote.upload(
                    ad.id,
                    kind,
                    await self._local.resolve(reference),
                )
            return ad, kind, marker

        uploaded = await asyncio.gather(
            *(upload_one(ad, kind, reference) for ad, kind, reference in pending)
        )
        for ad, kind, marker in uploaded:
            setattr(ad, MEDIA_SPECS[kind].model_attribute, marker)
        return len(uploaded)

    async def open(
        self,
        stored_reference: str,
        kind: MediaKind,
        *,
        ad_id: UUID,
        range_header: str | None = None,
    ) -> MediaPayload:
        if range_header is not None:
            validate_range_syntax(range_header)
        if is_s3_reference(stored_reference):
            return await self._require_remote().open(
                stored_reference,
                kind,
                ad_id,
                range_header,
            )
        return await self._local.open(stored_reference, kind, range_header)

    async def head(
        self,
        stored_reference: str,
        kind: MediaKind,
        *,
        ad_id: UUID,
    ) -> MediaPayload:
        if is_s3_reference(stored_reference):
            return await self._require_remote().head(stored_reference, kind, ad_id)
        return await self._local.head(stored_reference, kind)

    async def delete_object(self, stored_reference: str) -> None:
        if is_s3_reference(stored_reference):
            await self._require_remote().delete(stored_reference)

    def _require_remote(self) -> RemoteMediaGateway:
        if self._remote is None:
            raise MediaStorageError("S3 media client is not configured")
        return self._remote


class MediaService:
    def __init__(
        self,
        references: AdMediaReferenceReader,
        storage: MediaAccess,
        signer: MediaLinkSigner,
    ) -> None:
        self._references = references
        self._storage = storage
        self._signer = signer

    async def get_media(
        self,
        ad_id: UUID,
        kind: MediaKind,
        token: str,
        *,
        range_header: str | None = None,
        head_only: bool = False,
    ) -> MediaPayload:
        self._signer.verify_token(token, ad_id, kind)
        reference = await self._references.reference_for(ad_id, kind)
        if not reference:
            raise MediaNotFoundError("media does not exist")
        if head_only:
            return await self._storage.head(reference, kind, ad_id=ad_id)
        return await self._storage.open(
            reference,
            kind,
            ad_id=ad_id,
            range_header=range_header,
        )

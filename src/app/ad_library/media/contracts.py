from __future__ import annotations

from pathlib import Path
from typing import Protocol
from uuid import UUID

from .models import MediaKind, MediaPayload


class AdMediaOwner(Protocol):
    id: UUID
    screenshot_path: str | None
    landing_screenshot_path: str | None
    video_path: str | None
    landing_archive_path: str | None


class AdMediaReferenceReader(Protocol):
    async def reference_for(self, ad_id: UUID, kind: MediaKind) -> str | None: ...


class LocalMediaGateway(Protocol):
    async def resolve(self, stored_reference: str) -> Path: ...

    async def open(
        self,
        stored_reference: str,
        kind: MediaKind,
        range_header: str | None,
    ) -> MediaPayload: ...

    async def head(self, stored_reference: str, kind: MediaKind) -> MediaPayload: ...


class RemoteMediaGateway(Protocol):
    async def upload(self, ad_id: UUID, kind: MediaKind, source: Path) -> str: ...

    async def open(
        self,
        stored_reference: str,
        kind: MediaKind,
        ad_id: UUID,
        range_header: str | None,
    ) -> MediaPayload: ...

    async def head(
        self,
        stored_reference: str,
        kind: MediaKind,
        ad_id: UUID,
    ) -> MediaPayload: ...

    async def delete(self, stored_reference: str) -> None: ...


class MediaLinkSigner(Protocol):
    def url_for(
        self,
        ad_id: UUID,
        kind: MediaKind,
        stored_reference: str | None,
        *,
        now: int | None = None,
    ) -> str | None: ...

    def verify_token(
        self,
        token: str,
        ad_id: UUID,
        kind: MediaKind,
        *,
        now: int | None = None,
    ) -> int: ...


class MediaAccess(Protocol):
    async def open(
        self,
        stored_reference: str,
        kind: MediaKind,
        *,
        ad_id: UUID,
        range_header: str | None = None,
    ) -> MediaPayload: ...

    async def head(
        self,
        stored_reference: str,
        kind: MediaKind,
        *,
        ad_id: UUID,
    ) -> MediaPayload: ...

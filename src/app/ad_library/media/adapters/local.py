from __future__ import annotations

import asyncio
from pathlib import Path

from ..exceptions import MediaNotFoundError
from ..models import MediaKind, MediaPayload
from ..paths.validation import LocalPathPolicy, content_type
from ..ranges import resolve_local_range
from ..streaming import EmptyBody, LimitedReader


class LocalMediaStorage:
    def __init__(self, data_dir: Path) -> None:
        self._paths = LocalPathPolicy(data_dir)

    async def resolve(self, stored_reference: str) -> Path:
        return await asyncio.to_thread(self._paths.resolve, stored_reference)

    async def open(
        self,
        stored_reference: str,
        kind: MediaKind,
        range_header: str | None,
    ) -> MediaPayload:
        return await asyncio.to_thread(
            self._open,
            stored_reference,
            kind,
            range_header,
        )

    async def head(self, stored_reference: str, kind: MediaKind) -> MediaPayload:
        return await asyncio.to_thread(self._head, stored_reference, kind)

    def _open(
        self,
        stored_reference: str,
        kind: MediaKind,
        range_header: str | None,
    ) -> MediaPayload:
        path = self._paths.resolve(stored_reference)
        if not path.is_file():
            raise MediaNotFoundError("local media does not exist")
        total_size = path.stat().st_size
        if range_header is None:
            return MediaPayload(
                body=path.open("rb"),
                status_code=200,
                content_length=total_size,
                content_type=content_type(kind, path.suffix),
                total_size=total_size,
            )
        start, end = resolve_local_range(range_header, total_size)
        stream = path.open("rb")
        stream.seek(start)
        return MediaPayload(
            body=LimitedReader(stream, end - start + 1),
            status_code=206,
            content_length=end - start + 1,
            content_type=content_type(kind, path.suffix),
            content_range=f"bytes {start}-{end}/{total_size}",
            total_size=total_size,
        )

    def _head(self, stored_reference: str, kind: MediaKind) -> MediaPayload:
        path = self._paths.resolve(stored_reference)
        if not path.is_file():
            raise MediaNotFoundError("local media does not exist")
        content_length = path.stat().st_size
        return MediaPayload(
            body=EmptyBody(),
            status_code=200,
            content_length=content_length,
            content_type=content_type(kind, path.suffix),
            total_size=content_length,
        )

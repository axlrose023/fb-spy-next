from __future__ import annotations

from collections.abc import Iterator
from typing import Any, BinaryIO


class LimitedReader:
    def __init__(self, stream: BinaryIO, remaining: int) -> None:
        self._stream = stream
        self._remaining = remaining

    def read(self, size: int = -1) -> bytes:
        if self._remaining <= 0:
            return b""
        requested = self._remaining if size < 0 else min(size, self._remaining)
        chunk = self._stream.read(requested)
        self._remaining -= len(chunk)
        return chunk

    def close(self) -> None:
        self._stream.close()


class EmptyBody:
    def read(self, _size: int = -1) -> bytes:
        return b""

    def close(self) -> None:
        pass


def iter_media_body(body: Any, chunk_size: int = 256 * 1024) -> Iterator[bytes]:
    try:
        while chunk := body.read(chunk_size):
            yield chunk
    finally:
        body.close()

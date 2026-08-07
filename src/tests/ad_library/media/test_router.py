from __future__ import annotations

import io
from typing import cast
from uuid import UUID, uuid4

import pytest
from fastapi import HTTPException
from starlette.requests import Request
from starlette.responses import Response, StreamingResponse

from app.ad_library.media.exceptions import (
    MediaNotFoundError,
    MediaRangeError,
    MediaStorageError,
    MediaTokenError,
)
from app.ad_library.media.models import MediaKind, MediaPayload
from app.ad_library.media.router import get_ad_media
from app.ad_library.media.service import MediaService

pytestmark = pytest.mark.unit


class StubMediaService:
    def __init__(
        self,
        payload: MediaPayload | None = None,
        error: Exception | None = None,
    ) -> None:
        self.payload = payload
        self.error = error
        self.calls: list[tuple[str | None, bool]] = []

    async def get_media(
        self,
        ad_id: UUID,
        kind: MediaKind,
        token: str,
        *,
        range_header: str | None = None,
        head_only: bool = False,
    ) -> MediaPayload:
        del ad_id, kind, token
        self.calls.append((range_header, head_only))
        if self.error is not None:
            raise self.error
        assert self.payload is not None
        return self.payload


def request(method: str, range_header: str | None = None) -> Request:
    headers = [] if range_header is None else [(b"range", range_header.encode())]
    return Request({"type": "http", "method": method, "headers": headers})


async def response_body(response: StreamingResponse) -> bytes:
    result = bytearray()
    async for chunk in response.body_iterator:
        result.extend(chunk.encode() if isinstance(chunk, str) else chunk)
    return bytes(result)


def media_service(stub: StubMediaService) -> MediaService:
    return cast(MediaService, stub)


async def test_media_router_streams_backend_payload_with_safe_headers() -> None:
    ad_id = uuid4()
    body = io.BytesIO(b"video")
    service = StubMediaService(
        MediaPayload(
            body=body,
            status_code=206,
            content_length=5,
            content_type="video/mp4",
            content_range="bytes 0-4/5",
        )
    )

    response = await get_ad_media(
        request("GET", "bytes=0-4"),
        media_service(service),
        ad_id,
        MediaKind.VIDEO,
        "x" * 45,
    )

    assert isinstance(response, StreamingResponse)
    assert response.status_code == 206
    assert response.headers["content-range"] == "bytes 0-4/5"
    assert response.headers["cross-origin-resource-policy"] == "same-origin"
    assert "s3" not in str(response.headers).casefold()
    assert await response_body(response) == b"video"
    assert body.closed
    assert service.calls == [("bytes=0-4", False)]


async def test_media_router_head_closes_body_without_streaming() -> None:
    body = io.BytesIO(b"image")
    service = StubMediaService(
        MediaPayload(
            body=body,
            status_code=200,
            content_length=5,
            content_type="image/png",
        )
    )

    response = await get_ad_media(
        request("HEAD"),
        media_service(service),
        uuid4(),
        MediaKind.SCREENSHOT,
        "x" * 45,
    )

    assert isinstance(response, Response)
    assert not isinstance(response, StreamingResponse)
    assert body.closed
    assert service.calls == [(None, True)]


@pytest.mark.parametrize(
    ("error", "status", "detail"),
    [
        (MediaTokenError(), 403, "Invalid media link"),
        (MediaNotFoundError(), 404, "Media not found"),
        (MediaStorageError(), 502, "Media storage is temporarily unavailable"),
    ],
)
async def test_media_router_maps_module_errors(
    error: Exception,
    status: int,
    detail: str,
) -> None:
    with pytest.raises(HTTPException) as raised:
        await get_ad_media(
            request("GET"),
            media_service(StubMediaService(error=error)),
            uuid4(),
            MediaKind.SCREENSHOT,
            "x" * 45,
        )

    assert raised.value.status_code == status
    assert raised.value.detail == detail


async def test_media_router_maps_unsatisfied_range_with_size() -> None:
    with pytest.raises(HTTPException) as raised:
        await get_ad_media(
            request("GET", "bytes=9-10"),
            media_service(StubMediaService(error=MediaRangeError(5))),
            uuid4(),
            MediaKind.VIDEO,
            "x" * 45,
        )

    assert raised.value.status_code == 416
    assert raised.value.headers == {"Content-Range": "bytes */5"}

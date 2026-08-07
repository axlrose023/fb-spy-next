from __future__ import annotations

from pathlib import Path
from typing import Never
from uuid import UUID, uuid4

import pytest
from botocore.exceptions import ClientError  # type: ignore[import-untyped]

from app.ad_library.media.adapters.s3 import S3MediaStorage
from app.ad_library.media.exceptions import (
    MediaNotFoundError,
    MediaRangeError,
    MediaStorageError,
)
from app.ad_library.media.models import MediaKind

pytestmark = pytest.mark.unit


def client_error(status: int, code: str, operation: str) -> ClientError:
    return ClientError(
        {
            "Error": {"Code": code},
            "ResponseMetadata": {"HTTPStatusCode": status},
        },
        operation,
    )


class FailingClient:
    def __init__(
        self,
        *,
        read_error: ClientError | None = None,
        head_error: ClientError | None = None,
        delete_error: ClientError | None = None,
    ) -> None:
        self.read_error = read_error
        self.head_error = head_error
        self.delete_error = delete_error

    def get_object(self, **_kwargs: object) -> Never:
        assert self.read_error is not None
        raise self.read_error

    def head_object(self, **_kwargs: object) -> Never:
        assert self.head_error is not None
        raise self.head_error

    def delete_object(self, **_kwargs: object) -> Never:
        assert self.delete_error is not None
        raise self.delete_error


def storage(client: FailingClient) -> S3MediaStorage:
    return S3MediaStorage(
        endpoint_url="https://s3.example.test",
        region="test",
        bucket="private-media",
        access_key_id="access",
        write_secret="write-secret",
        read_secret="read-secret",
        object_prefix="ads",
        multipart_threshold_mb=5,
        multipart_chunk_mb=5,
        multipart_concurrency=1,
        write_client=client,
        read_client=client,
    )


def reference(ad_id: UUID) -> str:
    return f"s3:ads/{ad_id}/videos/creative.mp4"


@pytest.mark.parametrize(
    ("status", "code", "expected"),
    [
        (404, "NoSuchKey", MediaNotFoundError),
        (416, "InvalidRange", MediaRangeError),
        (500, "InternalError", MediaStorageError),
    ],
)
async def test_s3_open_translates_provider_errors(
    status: int,
    code: str,
    expected: type[Exception],
) -> None:
    ad_id = uuid4()
    adapter = storage(FailingClient(read_error=client_error(status, code, "GetObject")))

    with pytest.raises(expected):
        await adapter.open(reference(ad_id), MediaKind.VIDEO, ad_id, "bytes=0-1")


@pytest.mark.parametrize(
    ("status", "code", "expected"),
    [
        (404, "NoSuchKey", MediaNotFoundError),
        (500, "InternalError", MediaStorageError),
    ],
)
async def test_s3_head_translates_provider_errors(
    status: int,
    code: str,
    expected: type[Exception],
) -> None:
    ad_id = uuid4()
    adapter = storage(
        FailingClient(head_error=client_error(status, code, "HeadObject"))
    )

    with pytest.raises(expected):
        await adapter.head(reference(ad_id), MediaKind.VIDEO, ad_id)


async def test_s3_delete_translates_provider_error() -> None:
    ad_id = uuid4()
    adapter = storage(
        FailingClient(delete_error=client_error(403, "AccessDenied", "DeleteObject"))
    )

    with pytest.raises(MediaStorageError, match="delete"):
        await adapter.delete(reference(ad_id))


async def test_s3_upload_rejects_missing_local_source(tmp_path: Path) -> None:
    adapter = storage(FailingClient())

    with pytest.raises(MediaNotFoundError, match="source"):
        await adapter.upload(uuid4(), MediaKind.SCREENSHOT, tmp_path / "missing.png")

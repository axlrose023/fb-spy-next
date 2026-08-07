from __future__ import annotations

import asyncio
import logging
from pathlib import Path, PurePosixPath
from typing import Any, Never
from uuid import UUID

import boto3  # type: ignore[import-untyped]
from boto3.exceptions import S3UploadFailedError  # type: ignore[import-untyped]
from boto3.s3.transfer import TransferConfig  # type: ignore[import-untyped]
from botocore.config import Config as BotocoreConfig  # type: ignore[import-untyped]
from botocore.exceptions import (  # type: ignore[import-untyped]
    BotoCoreError,
    ClientError,
)

from ..exceptions import MediaNotFoundError, MediaRangeError, MediaStorageError
from ..models import MediaKind, MediaPayload
from ..paths.object_keys import ObjectKeyPolicy
from ..paths.validation import content_type
from ..ranges import total_size_from_content_range
from ..streaming import EmptyBody

logger = logging.getLogger(__name__)
_STORAGE_SDK_LOGGERS = ("boto3", "botocore", "s3transfer", "urllib3")


class S3MediaStorage:
    def __init__(
        self,
        *,
        endpoint_url: str,
        region: str,
        bucket: str,
        access_key_id: str,
        write_secret: str,
        read_secret: str,
        object_prefix: str,
        multipart_threshold_mb: int,
        multipart_chunk_mb: int,
        multipart_concurrency: int,
        write_client: Any | None = None,
        read_client: Any | None = None,
    ) -> None:
        for logger_name in _STORAGE_SDK_LOGGERS:
            logging.getLogger(logger_name).setLevel(logging.WARNING)
        self._endpoint_url = endpoint_url
        self._region = region
        self._bucket = bucket
        self._access_key_id = access_key_id
        self._keys = ObjectKeyPolicy(object_prefix)
        self._transfer = TransferConfig(
            multipart_threshold=multipart_threshold_mb * 1024 * 1024,
            multipart_chunksize=multipart_chunk_mb * 1024 * 1024,
            max_concurrency=multipart_concurrency,
            use_threads=True,
        )
        self._write_client = write_client or self._create_client(write_secret)
        if read_client is not None:
            self._read_client = read_client
        elif write_client is not None:
            self._read_client = write_client
        else:
            self._read_client = self._create_client(read_secret or write_secret)

    async def upload(self, ad_id: UUID, kind: MediaKind, source: Path) -> str:
        return await asyncio.to_thread(self._upload, ad_id, kind, source)

    async def open(
        self,
        stored_reference: str,
        kind: MediaKind,
        ad_id: UUID,
        range_header: str | None,
    ) -> MediaPayload:
        return await asyncio.to_thread(
            self._open,
            stored_reference,
            kind,
            ad_id,
            range_header,
        )

    async def head(
        self,
        stored_reference: str,
        kind: MediaKind,
        ad_id: UUID,
    ) -> MediaPayload:
        return await asyncio.to_thread(self._head, stored_reference, kind, ad_id)

    async def delete(self, stored_reference: str) -> None:
        key = self._keys.key_for_delete(stored_reference)
        try:
            await asyncio.to_thread(
                self._write_client.delete_object,
                Bucket=self._bucket,
                Key=key,
            )
        except (BotoCoreError, ClientError) as exc:
            raise MediaStorageError("failed to delete S3 media object") from exc

    def _upload(self, ad_id: UUID, kind: MediaKind, source: Path) -> str:
        if not source.is_file():
            raise MediaNotFoundError("local media source does not exist")
        key = self._keys.build(ad_id, kind, source.suffix)
        source_size = source.stat().st_size
        try:
            self._write_client.upload_file(
                str(source),
                self._bucket,
                key,
                ExtraArgs={"ContentType": content_type(kind, source.suffix)},
                Config=self._transfer,
            )
            metadata = self._write_client.head_object(Bucket=self._bucket, Key=key)
        except (BotoCoreError, ClientError, OSError, S3UploadFailedError) as exc:
            raise MediaStorageError("failed to upload media object to S3") from exc
        if int(metadata.get("ContentLength") or -1) != source_size:
            raise MediaStorageError("S3 media size verification failed")
        logger.info(
            "Uploaded ad media ad_id=%s kind=%s bytes=%s",
            ad_id,
            kind.value,
            source_size,
        )
        return self._keys.reference(key)

    def _open(
        self,
        stored_reference: str,
        kind: MediaKind,
        ad_id: UUID,
        range_header: str | None,
    ) -> MediaPayload:
        key = self._keys.key_for_read(stored_reference, kind, ad_id)
        kwargs: dict[str, Any] = {"Bucket": self._bucket, "Key": key}
        if range_header:
            kwargs["Range"] = range_header
        try:
            response = self._read_client.get_object(**kwargs)
        except ClientError as exc:
            self._raise_read_error(exc)
        content_range = response.get("ContentRange")
        content_length = int(response.get("ContentLength") or 0)
        total_size = total_size_from_content_range(content_range)
        if total_size is None and not content_range:
            total_size = content_length
        return MediaPayload(
            body=response["Body"],
            status_code=int(
                response.get("ResponseMetadata", {}).get("HTTPStatusCode")
                or (206 if content_range else 200)
            ),
            content_length=content_length,
            content_type=content_type(kind, PurePosixPath(key).suffix),
            content_range=content_range,
            total_size=total_size,
        )

    def _head(
        self,
        stored_reference: str,
        kind: MediaKind,
        ad_id: UUID,
    ) -> MediaPayload:
        key = self._keys.key_for_read(stored_reference, kind, ad_id)
        try:
            response = self._read_client.head_object(Bucket=self._bucket, Key=key)
        except ClientError as exc:
            status, code = self._error_details(exc)
            if status == 404 or code == "NoSuchKey":
                raise MediaNotFoundError("media object does not exist") from exc
            raise MediaStorageError("failed to read S3 media metadata") from exc
        content_length = int(response.get("ContentLength") or 0)
        return MediaPayload(
            body=EmptyBody(),
            status_code=200,
            content_length=content_length,
            content_type=content_type(kind, PurePosixPath(key).suffix),
            total_size=content_length,
        )

    def _raise_read_error(self, error: ClientError) -> Never:
        status, code = self._error_details(error)
        if status == 404 or code == "NoSuchKey":
            raise MediaNotFoundError("media object does not exist") from error
        if status == 416 or code in {
            "InvalidRange",
            "RequestedRangeNotSatisfiable",
        }:
            raise MediaRangeError from error
        raise MediaStorageError("failed to read S3 media object") from error

    @staticmethod
    def _error_details(error: ClientError) -> tuple[int, str]:
        status = int(
            error.response.get("ResponseMetadata", {}).get("HTTPStatusCode", 0)
        )
        code = str(error.response.get("Error", {}).get("Code", ""))
        return status, code

    def _create_client(self, secret_access_key: str) -> Any:
        return boto3.client(
            "s3",
            endpoint_url=self._endpoint_url,
            region_name=self._region,
            aws_access_key_id=self._access_key_id,
            aws_secret_access_key=secret_access_key,
            config=BotocoreConfig(
                signature_version="s3v4",
                s3={"addressing_style": "path"},
                retries={"max_attempts": 5, "mode": "standard"},
                connect_timeout=10,
                read_timeout=120,
                tcp_keepalive=True,
                request_checksum_calculation="when_required",
                response_checksum_validation="when_required",
            ),
        )

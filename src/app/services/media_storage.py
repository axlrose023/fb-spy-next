from __future__ import annotations

import asyncio
import base64
import hashlib
import hmac
import logging
import mimetypes
import re
import time
from collections.abc import Iterator
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path, PurePosixPath
from typing import TYPE_CHECKING, Any, BinaryIO
from uuid import UUID

import boto3
from boto3.exceptions import S3UploadFailedError
from boto3.s3.transfer import TransferConfig
from botocore.config import Config as BotocoreConfig
from botocore.exceptions import BotoCoreError, ClientError

from app.settings import Config

if TYPE_CHECKING:
    from app.api.modules.ads.models import FacebookAd

logger = logging.getLogger(__name__)

S3_REFERENCE_PREFIX = "s3:"
_RANGE_RE = re.compile(r"bytes=(\d*)-(\d*)\Z")
_TOKEN_RE = re.compile(r"(\d{1,12})\.([A-Za-z0-9_-]{43})\Z")
_STORAGE_SDK_LOGGERS = ("boto3", "botocore", "s3transfer", "urllib3")


class MediaKind(StrEnum):
    SCREENSHOT = "screenshot"
    LANDING_SCREENSHOT = "landing-screenshot"
    VIDEO = "video"
    LANDING_ARCHIVE = "landing-archive"


@dataclass(frozen=True)
class MediaSpec:
    model_attribute: str
    directory: str
    object_stem: str
    default_suffix: str
    default_content_type: str
    attachment: bool = False


MEDIA_SPECS: dict[MediaKind, MediaSpec] = {
    MediaKind.SCREENSHOT: MediaSpec(
        model_attribute="screenshot_path",
        directory="screenshots",
        object_stem="feed",
        default_suffix=".png",
        default_content_type="image/png",
    ),
    MediaKind.LANDING_SCREENSHOT: MediaSpec(
        model_attribute="landing_screenshot_path",
        directory="screenshots",
        object_stem="landing-full",
        default_suffix=".png",
        default_content_type="image/png",
    ),
    MediaKind.VIDEO: MediaSpec(
        model_attribute="video_path",
        directory="videos",
        object_stem="creative",
        default_suffix=".mp4",
        default_content_type="video/mp4",
    ),
    MediaKind.LANDING_ARCHIVE: MediaSpec(
        model_attribute="landing_archive_path",
        directory="archives",
        object_stem="landing",
        default_suffix=".zip",
        default_content_type="application/zip",
        attachment=True,
    ),
}

_ALLOWED_SUFFIXES: dict[MediaKind, set[str]] = {
    MediaKind.SCREENSHOT: {".png", ".jpg", ".jpeg", ".webp"},
    MediaKind.LANDING_SCREENSHOT: {".png", ".jpg", ".jpeg", ".webp"},
    MediaKind.VIDEO: {".mp4", ".webm", ".mov"},
    MediaKind.LANDING_ARCHIVE: {".zip"},
}


class MediaTokenError(ValueError):
    pass


class MediaNotFoundError(FileNotFoundError):
    pass


class MediaRangeError(ValueError):
    def __init__(self, total_size: int | None = None) -> None:
        self.total_size = total_size
        super().__init__("requested media range is not satisfiable")


class MediaStorageError(RuntimeError):
    pass


@dataclass
class MediaPayload:
    body: BinaryIO | Any
    status_code: int
    content_length: int
    content_type: str
    content_range: str | None = None
    total_size: int | None = None


class MediaURLSigner:
    def __init__(self, config: Config) -> None:
        self._secret = config.media.signing_secret.get_secret_value().encode()
        self._ttl_seconds = config.media.signed_url_ttl_seconds
        self._public_path = config.media.public_path.rstrip("/")

    @property
    def ttl_seconds(self) -> int:
        return self._ttl_seconds

    def url_for(
        self,
        ad_id: UUID,
        kind: MediaKind,
        stored_reference: str | None,
        *,
        now: int | None = None,
    ) -> str | None:
        if not stored_reference:
            return None
        token = self.create_token(ad_id, kind, now=now)
        return f"{self._public_path}/ads/{ad_id}/{kind.value}?token={token}"

    def create_token(
        self,
        ad_id: UUID,
        kind: MediaKind,
        *,
        now: int | None = None,
    ) -> str:
        issued_at = int(time.time()) if now is None else int(now)
        expires_at = issued_at + self._ttl_seconds
        signature = self._signature(ad_id, kind, expires_at)
        return f"{expires_at}.{signature}"

    def verify_token(
        self,
        token: str,
        ad_id: UUID,
        kind: MediaKind,
        *,
        now: int | None = None,
    ) -> int:
        match = _TOKEN_RE.fullmatch(token)
        if match is None:
            raise MediaTokenError("invalid media token")
        expires_at = int(match.group(1))
        current = int(time.time()) if now is None else int(now)
        if expires_at < current:
            raise MediaTokenError("expired media token")
        if expires_at > current + self._ttl_seconds + 60:
            raise MediaTokenError("media token expiry exceeds the configured limit")
        expected = self._signature(ad_id, kind, expires_at)
        if not hmac.compare_digest(match.group(2), expected):
            raise MediaTokenError("invalid media token")
        return expires_at

    def _signature(self, ad_id: UUID, kind: MediaKind, expires_at: int) -> str:
        payload = f"v1\n{ad_id}\n{kind.value}\n{expires_at}".encode()
        digest = hmac.new(self._secret, payload, hashlib.sha256).digest()
        return base64.urlsafe_b64encode(digest).rstrip(b"=").decode("ascii")


class MediaStorage:
    def __init__(
        self,
        config: Config,
        *,
        s3_client: Any | None = None,
        s3_read_client: Any | None = None,
    ) -> None:
        for logger_name in _STORAGE_SDK_LOGGERS:
            logging.getLogger(logger_name).setLevel(logging.WARNING)
        self._config = config
        self._media = config.media
        self._data_dir = config.facebook.data_dir.expanduser().resolve()
        self._write_client = s3_client
        self._read_client = s3_read_client or s3_client
        self._transfer_config = TransferConfig(
            multipart_threshold=self._media.multipart_threshold_mb * 1024 * 1024,
            multipart_chunksize=self._media.multipart_chunk_mb * 1024 * 1024,
            max_concurrency=self._media.multipart_concurrency,
            use_threads=True,
        )
        if self._media.backend == "s3":
            if self._write_client is None:
                self._write_client = self._create_s3_client(
                    self._media.secret_access_key.get_secret_value()
                )
            if self._read_client is None:
                read_secret = (
                    self._media.read_only_secret_access_key.get_secret_value()
                    or self._media.secret_access_key.get_secret_value()
                )
                self._read_client = self._create_s3_client(read_secret)

    def _create_s3_client(self, secret_access_key: str) -> Any:
        return boto3.client(
            "s3",
            endpoint_url=self._media.endpoint_url,
            region_name=self._media.region,
            aws_access_key_id=self._media.access_key_id,
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

    @property
    def backend(self) -> str:
        return self._media.backend

    async def upload_ads(
        self,
        ads: list[FacebookAd],
        *,
        relevance_verified: bool,
    ) -> int:
        if self._media.backend != "s3" or not ads:
            return 0
        if not relevance_verified:
            raise MediaStorageError(
                "refusing to upload media without explicit relevance verification"
            )

        semaphore = asyncio.Semaphore(self._media.upload_concurrency)
        pending: list[tuple[FacebookAd, MediaKind, str]] = []
        for ad in ads:
            for kind, spec in MEDIA_SPECS.items():
                reference = getattr(ad, spec.model_attribute)
                if reference and not is_s3_reference(reference):
                    pending.append((ad, kind, reference))

        async def upload_one(
            ad: FacebookAd,
            kind: MediaKind,
            reference: str,
        ) -> tuple[FacebookAd, MediaKind, str]:
            async with semaphore:
                marker = await asyncio.to_thread(
                    self._upload_one,
                    ad.id,
                    kind,
                    reference,
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
            _validate_range_syntax(range_header)
        if is_s3_reference(stored_reference):
            return await asyncio.to_thread(
                self._open_s3,
                stored_reference,
                kind,
                ad_id,
                range_header,
            )
        return await asyncio.to_thread(
            self._open_local,
            stored_reference,
            kind,
            range_header,
        )

    async def head(
        self,
        stored_reference: str,
        kind: MediaKind,
        *,
        ad_id: UUID,
    ) -> MediaPayload:
        if is_s3_reference(stored_reference):
            return await asyncio.to_thread(
                self._head_s3,
                stored_reference,
                kind,
                ad_id,
            )
        return await asyncio.to_thread(self._head_local, stored_reference, kind)

    async def delete_object(self, stored_reference: str) -> None:
        if not is_s3_reference(stored_reference):
            return
        key = self._object_key(stored_reference)
        try:
            await asyncio.to_thread(
                self._require_write_client().delete_object,
                Bucket=self._media.bucket,
                Key=key,
            )
        except (BotoCoreError, ClientError) as exc:
            raise MediaStorageError("failed to delete S3 media object") from exc

    def _upload_one(
        self,
        ad_id: UUID,
        kind: MediaKind,
        stored_reference: str,
    ) -> str:
        source = self._local_path(stored_reference)
        if not source.is_file():
            raise MediaNotFoundError("local media source does not exist")
        spec = MEDIA_SPECS[kind]
        suffix = _safe_suffix(source.suffix, kind)
        key = (
            f"{self._media.object_prefix.strip('/')}/{ad_id}/"
            f"{spec.directory}/{spec.object_stem}{suffix}"
        )
        content_type = _content_type(kind, suffix)
        source_size = source.stat().st_size
        client = self._require_write_client()
        try:
            client.upload_file(
                str(source),
                self._media.bucket,
                key,
                ExtraArgs={"ContentType": content_type},
                Config=self._transfer_config,
            )
            metadata = client.head_object(Bucket=self._media.bucket, Key=key)
        except (BotoCoreError, ClientError, OSError, S3UploadFailedError) as exc:
            raise MediaStorageError("failed to upload media object to S3") from exc
        remote_size = int(metadata.get("ContentLength") or -1)
        if remote_size != source_size:
            raise MediaStorageError("S3 media size verification failed")
        logger.info(
            "Uploaded ad media ad_id=%s kind=%s bytes=%s",
            ad_id,
            kind.value,
            source_size,
        )
        return f"{S3_REFERENCE_PREFIX}{key}"

    def _open_s3(
        self,
        stored_reference: str,
        kind: MediaKind,
        ad_id: UUID,
        range_header: str | None,
    ) -> MediaPayload:
        key = self._object_key(stored_reference, kind, ad_id)
        kwargs: dict[str, Any] = {"Bucket": self._media.bucket, "Key": key}
        if range_header:
            kwargs["Range"] = range_header
        try:
            response = self._require_read_client().get_object(**kwargs)
        except ClientError as exc:
            status = int(
                exc.response.get("ResponseMetadata", {}).get("HTTPStatusCode", 0)
            )
            code = str(exc.response.get("Error", {}).get("Code", ""))
            if status == 404 or code == "NoSuchKey":
                raise MediaNotFoundError("media object does not exist") from exc
            if status == 416 or code in {
                "InvalidRange",
                "RequestedRangeNotSatisfiable",
            }:
                raise MediaRangeError() from exc
            raise MediaStorageError("failed to read S3 media object") from exc

        content_range = response.get("ContentRange")
        content_length = int(response.get("ContentLength") or 0)
        total_size = _total_size_from_content_range(content_range)
        if total_size is None and not content_range:
            total_size = content_length
        return MediaPayload(
            body=response["Body"],
            status_code=int(
                response.get("ResponseMetadata", {}).get("HTTPStatusCode")
                or (206 if content_range else 200)
            ),
            content_length=content_length,
            content_type=_content_type(kind, PurePosixPath(key).suffix),
            content_range=content_range,
            total_size=total_size,
        )

    def _head_s3(
        self,
        stored_reference: str,
        kind: MediaKind,
        ad_id: UUID,
    ) -> MediaPayload:
        key = self._object_key(stored_reference, kind, ad_id)
        try:
            response = self._require_read_client().head_object(
                Bucket=self._media.bucket,
                Key=key,
            )
        except ClientError as exc:
            status = int(
                exc.response.get("ResponseMetadata", {}).get("HTTPStatusCode", 0)
            )
            code = str(exc.response.get("Error", {}).get("Code", ""))
            if status == 404 or code == "NoSuchKey":
                raise MediaNotFoundError("media object does not exist") from exc
            raise MediaStorageError("failed to read S3 media metadata") from exc
        content_length = int(response.get("ContentLength") or 0)
        return MediaPayload(
            body=_EmptyBody(),
            status_code=200,
            content_length=content_length,
            content_type=_content_type(kind, PurePosixPath(key).suffix),
            total_size=content_length,
        )

    def _open_local(
        self,
        stored_reference: str,
        kind: MediaKind,
        range_header: str | None,
    ) -> MediaPayload:
        path = self._local_path(stored_reference)
        if not path.is_file():
            raise MediaNotFoundError("local media does not exist")
        total_size = path.stat().st_size
        stream = path.open("rb")
        if range_header is None:
            return MediaPayload(
                body=stream,
                status_code=200,
                content_length=total_size,
                content_type=_content_type(kind, path.suffix),
                total_size=total_size,
            )
        start, end = _resolve_local_range(range_header, total_size)
        stream.seek(start)
        return MediaPayload(
            body=_LimitedReader(stream, end - start + 1),
            status_code=206,
            content_length=end - start + 1,
            content_type=_content_type(kind, path.suffix),
            content_range=f"bytes {start}-{end}/{total_size}",
            total_size=total_size,
        )

    def _head_local(
        self,
        stored_reference: str,
        kind: MediaKind,
    ) -> MediaPayload:
        path = self._local_path(stored_reference)
        if not path.is_file():
            raise MediaNotFoundError("local media does not exist")
        content_length = path.stat().st_size
        return MediaPayload(
            body=_EmptyBody(),
            status_code=200,
            content_length=content_length,
            content_type=_content_type(kind, path.suffix),
            total_size=content_length,
        )

    def _local_path(self, stored_reference: str) -> Path:
        candidate = Path(stored_reference).expanduser()
        if not candidate.is_absolute():
            candidate = self._data_dir / candidate
        try:
            resolved = candidate.resolve(strict=True)
            resolved.relative_to(self._data_dir)
        except (FileNotFoundError, OSError, ValueError) as exc:
            raise MediaNotFoundError("invalid local media reference") from exc
        return resolved

    def _object_key(
        self,
        stored_reference: str,
        kind: MediaKind | None = None,
        expected_ad_id: UUID | None = None,
    ) -> str:
        key = stored_reference.removeprefix(S3_REFERENCE_PREFIX)
        path = PurePosixPath(key)
        prefix = self._media.object_prefix.strip("/")
        if (
            not key
            or path.is_absolute()
            or "//" in key
            or "\\" in key
            or "\x00" in key
            or any(part in {"", ".", ".."} for part in path.parts)
            or not key.startswith(f"{prefix}/")
        ):
            raise MediaNotFoundError("invalid S3 media reference")
        if kind is not None:
            prefix_parts = PurePosixPath(prefix).parts
            media_parts = path.parts[len(prefix_parts) :]
            spec = MEDIA_SPECS[kind]
            if len(media_parts) != 3:
                raise MediaNotFoundError("invalid S3 media reference")
            ad_id, directory, filename = media_parts
            try:
                object_ad_id = UUID(ad_id)
            except ValueError as exc:
                raise MediaNotFoundError("invalid S3 media reference") from exc
            suffix = PurePosixPath(filename).suffix.casefold()
            if (
                expected_ad_id is None
                or object_ad_id != expected_ad_id
                or directory != spec.directory
                or suffix not in _ALLOWED_SUFFIXES[kind]
                or filename != f"{spec.object_stem}{suffix}"
            ):
                raise MediaNotFoundError("invalid S3 media reference")
        return key

    def _require_write_client(self) -> Any:
        if self._write_client is None:
            raise MediaStorageError("S3 media write client is not configured")
        return self._write_client

    def _require_read_client(self) -> Any:
        if self._read_client is None:
            raise MediaStorageError("S3 media read client is not configured")
        return self._read_client


class _LimitedReader:
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


class _EmptyBody:
    def read(self, _size: int = -1) -> bytes:
        return b""

    def close(self) -> None:
        pass


def is_s3_reference(value: str | None) -> bool:
    return bool(value and value.startswith(S3_REFERENCE_PREFIX))


def iter_media_body(body: Any, chunk_size: int = 256 * 1024) -> Iterator[bytes]:
    try:
        while chunk := body.read(chunk_size):
            yield chunk
    finally:
        body.close()


def _validate_range_syntax(value: str) -> None:
    match = _RANGE_RE.fullmatch(value.strip())
    if match is None or not (match.group(1) or match.group(2)):
        raise MediaRangeError()


def _resolve_local_range(value: str, total_size: int) -> tuple[int, int]:
    match = _RANGE_RE.fullmatch(value.strip())
    if match is None:
        raise MediaRangeError(total_size)
    first, last = match.groups()
    if first:
        start = int(first)
        end = int(last) if last else total_size - 1
        if start >= total_size or end < start:
            raise MediaRangeError(total_size)
        return start, min(end, total_size - 1)
    suffix_length = int(last)
    if suffix_length <= 0 or total_size <= 0:
        raise MediaRangeError(total_size)
    return max(0, total_size - suffix_length), total_size - 1


def _safe_suffix(value: str, kind: MediaKind) -> str:
    suffix = value.casefold()
    return (
        suffix
        if suffix in _ALLOWED_SUFFIXES[kind]
        else MEDIA_SPECS[kind].default_suffix
    )


def _content_type(kind: MediaKind, suffix: str) -> str:
    safe_suffix = _safe_suffix(suffix, kind)
    guessed, _ = mimetypes.guess_type(f"file{safe_suffix}")
    if guessed:
        return guessed
    return MEDIA_SPECS[kind].default_content_type


def _total_size_from_content_range(value: str | None) -> int | None:
    if not value or "/" not in value:
        return None
    total = value.rsplit("/", 1)[-1]
    return int(total) if total.isdigit() else None

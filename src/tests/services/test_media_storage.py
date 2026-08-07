from __future__ import annotations

import io
import logging
from types import SimpleNamespace
from uuid import uuid4

import pytest

from app.services.media_storage import (
    MediaKind,
    MediaNotFoundError,
    MediaRangeError,
    MediaStorage,
    MediaStorageError,
    MediaTokenError,
    MediaURLSigner,
)
from app.settings import Config, FacebookConfig, JwtConfig, MediaStorageConfig


class FakeS3Client:
    def __init__(
        self,
        objects: dict[tuple[str, str], tuple[bytes, str]] | None = None,
    ) -> None:
        self.objects = objects if objects is not None else {}
        self.uploads: list[dict] = []
        self.reads: list[tuple[str, str]] = []
        self.deletes: list[tuple[str, str]] = []

    def upload_file(
        self,
        filename: str,
        bucket: str,
        key: str,
        *,
        ExtraArgs: dict,
        Config,
    ) -> None:
        del Config
        data = open(filename, "rb").read()
        content_type = ExtraArgs["ContentType"]
        self.objects[(bucket, key)] = (data, content_type)
        self.uploads.append(
            {
                "bucket": bucket,
                "key": key,
                "extra_args": ExtraArgs,
            }
        )

    def head_object(self, *, Bucket: str, Key: str) -> dict:
        data, content_type = self.objects[(Bucket, Key)]
        return {"ContentLength": len(data), "ContentType": content_type}

    def get_object(self, *, Bucket: str, Key: str, Range: str | None = None) -> dict:
        self.reads.append((Bucket, Key))
        data, content_type = self.objects[(Bucket, Key)]
        status = 200
        content_range = None
        if Range:
            first, last = Range.removeprefix("bytes=").split("-", 1)
            start = int(first) if first else max(0, len(data) - int(last))
            end = int(last) if first and last else len(data) - 1
            data = data[start : end + 1]
            content_range = f"bytes {start}-{end}/{len(self.objects[(Bucket, Key)][0])}"
            status = 206
        result = {
            "Body": io.BytesIO(data),
            "ContentLength": len(data),
            "ContentType": content_type,
            "ResponseMetadata": {"HTTPStatusCode": status},
        }
        if content_range:
            result["ContentRange"] = content_range
        return result

    def delete_object(self, *, Bucket: str, Key: str) -> None:
        self.deletes.append((Bucket, Key))
        self.objects.pop((Bucket, Key))


def _config(tmp_path, *, backend: str = "s3") -> Config:
    media = MediaStorageConfig(
        backend=backend,
        endpoint_url="https://s3.example.test" if backend == "s3" else "",
        region="test" if backend == "s3" else "",
        bucket="private-media" if backend == "s3" else "",
        access_key_id="test-access" if backend == "s3" else "",
        secret_access_key=(
            "test-storage-secret-not-used-by-the-fake" if backend == "s3" else ""
        ),
        read_only_secret_access_key=(
            "test-read-only-storage-secret-not-used-by-the-fake"
            if backend == "s3"
            else ""
        ),
        signing_secret="independent-test-signing-secret-at-least-32-characters",
    )
    return Config(
        env="local",
        media=media,
        facebook=FacebookConfig(data_dir=tmp_path),
    )


def test_media_url_token_is_backend_only_and_valid_for_30_days(tmp_path) -> None:
    config = _config(tmp_path)
    signer = MediaURLSigner(config)
    ad_id = uuid4()
    issued_at = 1_800_000_000

    url = signer.url_for(
        ad_id,
        MediaKind.LANDING_SCREENSHOT,
        "s3:ads/private/object.png",
        now=issued_at,
    )

    assert url is not None
    assert url.startswith(f"/media/ads/{ad_id}/landing-screenshot?token=")
    assert "s3" not in url
    assert config.media.bucket not in url
    assert config.media.endpoint_url not in url
    token = url.rsplit("=", 1)[-1]
    expires_at = signer.verify_token(
        token,
        ad_id,
        MediaKind.LANDING_SCREENSHOT,
        now=issued_at,
    )
    assert expires_at - issued_at == 30 * 24 * 60 * 60

    with pytest.raises(MediaTokenError):
        signer.verify_token(
            token,
            uuid4(),
            MediaKind.LANDING_SCREENSHOT,
            now=issued_at,
        )
    with pytest.raises(MediaTokenError):
        signer.verify_token(
            token,
            ad_id,
            MediaKind.VIDEO,
            now=issued_at,
        )
    with pytest.raises(MediaTokenError):
        signer.verify_token(
            token,
            ad_id,
            MediaKind.LANDING_SCREENSHOT,
            now=expires_at + 1,
        )


def test_media_storage_never_enables_sdk_wire_logging(tmp_path) -> None:
    logging.getLogger("botocore").setLevel(logging.DEBUG)

    MediaStorage(_config(tmp_path), s3_client=FakeS3Client())

    assert logging.getLogger("botocore").level == logging.WARNING


async def test_s3_upload_layout_integrity_and_ranged_read(tmp_path) -> None:
    config = _config(tmp_path)
    files = {
        "screens/feed.png": b"feed-image",
        "screens/landing.png": b"landing-image",
        "videos/creative.mp4": b"0123456789",
        "archives/landing.zip": b"PK\x03\x04archive",
    }
    for relative, data in files.items():
        path = tmp_path / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)

    ad_id = uuid4()
    ad = SimpleNamespace(
        id=ad_id,
        screenshot_path="screens/feed.png",
        landing_screenshot_path="screens/landing.png",
        video_path="videos/creative.mp4",
        landing_archive_path="archives/landing.zip",
    )
    client = FakeS3Client()
    storage = MediaStorage(config, s3_client=client)

    assert await storage.upload_ads([ad], relevance_verified=True) == 4
    assert ad.screenshot_path == f"s3:ads/{ad_id}/screenshots/feed.png"
    assert ad.landing_screenshot_path == f"s3:ads/{ad_id}/screenshots/landing-full.png"
    assert ad.video_path == f"s3:ads/{ad_id}/videos/creative.mp4"
    assert ad.landing_archive_path == f"s3:ads/{ad_id}/archives/landing.zip"
    assert all(
        set(upload["extra_args"]) == {"ContentType"} for upload in client.uploads
    )

    payload = await storage.open(
        ad.video_path,
        MediaKind.VIDEO,
        ad_id=ad_id,
        range_header="bytes=2-5",
    )
    assert payload.status_code == 206
    assert payload.content_length == 4
    assert payload.content_range == "bytes 2-5/10"
    assert payload.content_type == "video/mp4"
    assert payload.body.read() == b"2345"
    payload.body.close()

    await storage.delete_object(ad.video_path)
    assert (
        config.media.bucket,
        f"ads/{ad_id}/videos/creative.mp4",
    ) not in client.objects


async def test_s3_reads_use_read_only_client_and_writes_use_write_client(
    tmp_path,
) -> None:
    shared_objects: dict[tuple[str, str], tuple[bytes, str]] = {}
    write_client = FakeS3Client(shared_objects)
    read_client = FakeS3Client(shared_objects)
    storage = MediaStorage(
        _config(tmp_path),
        s3_client=write_client,
        s3_read_client=read_client,
    )
    ad_id = uuid4()
    source = tmp_path / "screens" / "feed.png"
    source.parent.mkdir(parents=True)
    source.write_bytes(b"feed-image")
    ad = SimpleNamespace(
        id=ad_id,
        screenshot_path="screens/feed.png",
        landing_screenshot_path=None,
        video_path=None,
        landing_archive_path=None,
    )

    assert await storage.upload_ads([ad], relevance_verified=True) == 1
    assert write_client.uploads
    assert not read_client.uploads

    payload = await storage.open(
        ad.screenshot_path,
        MediaKind.SCREENSHOT,
        ad_id=ad_id,
    )
    assert payload.body.read() == b"feed-image"
    payload.body.close()
    assert read_client.reads == [
        (
            config_bucket := _config(tmp_path).media.bucket,
            f"ads/{ad_id}/screenshots/feed.png",
        )
    ]
    assert not write_client.reads

    await storage.delete_object(ad.screenshot_path)
    assert write_client.deletes == [
        (config_bucket, f"ads/{ad_id}/screenshots/feed.png")
    ]
    assert not read_client.deletes


async def test_s3_upload_refuses_media_without_relevance_verification(
    tmp_path,
) -> None:
    storage = MediaStorage(_config(tmp_path), s3_client=FakeS3Client())
    ad = SimpleNamespace(
        id=uuid4(),
        screenshot_path=None,
        landing_screenshot_path=None,
        video_path=None,
        landing_archive_path=None,
    )

    with pytest.raises(MediaStorageError, match="relevance verification"):
        await storage.upload_ads([ad], relevance_verified=False)


async def test_local_storage_rejects_traversal_and_invalid_ranges(tmp_path) -> None:
    storage = MediaStorage(_config(tmp_path, backend="local"))
    path = tmp_path / "screens" / "feed.png"
    path.parent.mkdir(parents=True)
    path.write_bytes(b"image")

    with pytest.raises(MediaNotFoundError):
        await storage.open(
            "../outside.png",
            MediaKind.SCREENSHOT,
            ad_id=uuid4(),
        )
    with pytest.raises(MediaRangeError):
        await storage.open(
            "screens/feed.png",
            MediaKind.SCREENSHOT,
            ad_id=uuid4(),
            range_header="bytes=100-200",
        )
    with pytest.raises(MediaRangeError):
        await storage.open(
            "screens/feed.png",
            MediaKind.SCREENSHOT,
            ad_id=uuid4(),
            range_header="bytes=0-1,3-4",
        )


def test_production_rejects_default_media_signing_secret(tmp_path) -> None:
    with pytest.raises(ValueError, match="signing_secret must be changed"):
        Config(
            env="prod",
            jwt=JwtConfig(secret_key="secure-production-jwt-secret-at-least-32-bytes"),
            media=MediaStorageConfig(backend="local"),
            facebook=FacebookConfig(data_dir=tmp_path),
        )


def test_production_rejects_weak_jwt_secret(tmp_path) -> None:
    with pytest.raises(ValueError, match="jwt secret_key"):
        Config(
            env="prod",
            jwt=JwtConfig(secret_key="short"),
            media=MediaStorageConfig(
                backend="local",
                signing_secret="secure-production-media-signing-secret-32-bytes",
            ),
            facebook=FacebookConfig(data_dir=tmp_path),
        )


@pytest.mark.parametrize(
    ("read_secret", "match"),
    [
        ("", "required in production"),
        ("write-secret", "must differ from the write secret"),
        (
            "secure-production-media-signing-secret-32-bytes",
            "must differ from the read-only S3 secret",
        ),
    ],
)
def test_production_requires_independent_read_only_s3_secret(
    tmp_path,
    read_secret,
    match,
) -> None:
    with pytest.raises(ValueError, match=match):
        Config(
            env="prod",
            jwt=JwtConfig(secret_key="secure-production-jwt-secret-at-least-32-bytes"),
            media=MediaStorageConfig(
                backend="s3",
                endpoint_url="https://s3.example.test",
                region="test",
                bucket="private-media",
                access_key_id="test-access",
                secret_access_key="write-secret",
                read_only_secret_access_key=read_secret,
                signing_secret="secure-production-media-signing-secret-32-bytes",
            ),
            facebook=FacebookConfig(data_dir=tmp_path),
        )


@pytest.mark.parametrize(
    "public_path",
    ["//attacker.example/media", "/media?redirect=1", "/../media", "/"],
)
def test_media_public_path_rejects_external_or_ambiguous_urls(public_path) -> None:
    with pytest.raises(ValueError, match="absolute URL path"):
        MediaStorageConfig(public_path=public_path)


@pytest.mark.parametrize(
    "endpoint_url",
    [
        "http://s3.example.test",
        "https://user:password@s3.example.test",
        "https://s3.example.test/private-zone",
        "https://s3.example.test?bucket=private",
        "https://",
    ],
)
def test_s3_endpoint_must_be_a_plain_https_origin(endpoint_url) -> None:
    with pytest.raises(ValueError, match="HTTPS origin"):
        MediaStorageConfig(
            backend="s3",
            endpoint_url=endpoint_url,
            region="test-region",
            bucket="private-media",
            access_key_id="test-access",
            secret_access_key="test-secret",
        )


async def test_s3_reference_rejects_ambiguous_object_keys(tmp_path) -> None:
    storage = MediaStorage(_config(tmp_path), s3_client=FakeS3Client())

    for reference in (
        "s3:ads//object.png",
        "s3:ads/../object.png",
        "s3:other/object.png",
    ):
        with pytest.raises(MediaNotFoundError):
            await storage.open(
                reference,
                MediaKind.SCREENSHOT,
                ad_id=uuid4(),
            )


async def test_s3_reference_is_bound_to_expected_ad_media_layout(tmp_path) -> None:
    storage = MediaStorage(_config(tmp_path), s3_client=FakeS3Client())
    ad_id = uuid4()

    invalid_references = (
        "s3:ads/not-a-uuid/screenshots/feed.png",
        f"s3:ads/{ad_id}/screenshots/other.png",
        f"s3:ads/{ad_id}/screenshots/feed.exe",
        f"s3:ads/{ad_id}/screenshots/nested/feed.png",
        f"s3:ads/{ad_id}/archives/landing.zip",
    )
    for reference in invalid_references:
        with pytest.raises(MediaNotFoundError):
            await storage.open(
                reference,
                MediaKind.SCREENSHOT,
                ad_id=ad_id,
            )

    with pytest.raises(MediaNotFoundError):
        await storage.open(
            f"s3:ads/{ad_id}/screenshots/feed.png",
            MediaKind.SCREENSHOT,
            ad_id=uuid4(),
        )

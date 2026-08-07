from __future__ import annotations

from typing import Any

from app.settings import Config

from .adapters import LocalMediaStorage, S3MediaStorage
from .service import MediaStorage
from .signing import MediaSigningPolicy, MediaURLSigner


def configured_signer(config: Config) -> MediaURLSigner:
    return MediaURLSigner(
        MediaSigningPolicy(
            secret=config.media.signing_secret.get_secret_value(),
            ttl_seconds=config.media.signed_url_ttl_seconds,
            public_path=config.media.public_path,
        )
    )


def configured_storage(
    config: Config,
    *,
    s3_client: Any | None = None,
    s3_read_client: Any | None = None,
) -> MediaStorage:
    local = LocalMediaStorage(config.facebook.data_dir)
    remote = None
    if config.media.backend == "s3":
        remote = S3MediaStorage(
            endpoint_url=config.media.endpoint_url,
            region=config.media.region,
            bucket=config.media.bucket,
            access_key_id=config.media.access_key_id,
            write_secret=config.media.secret_access_key.get_secret_value(),
            read_secret=(
                config.media.read_only_secret_access_key.get_secret_value()
                or config.media.secret_access_key.get_secret_value()
            ),
            object_prefix=config.media.object_prefix,
            multipart_threshold_mb=config.media.multipart_threshold_mb,
            multipart_chunk_mb=config.media.multipart_chunk_mb,
            multipart_concurrency=config.media.multipart_concurrency,
            write_client=s3_client,
            read_client=s3_read_client,
        )
    return MediaStorage(
        local,
        remote,
        backend=config.media.backend,
        upload_concurrency=config.media.upload_concurrency,
    )

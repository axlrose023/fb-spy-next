import re
from typing import Literal

from pydantic import BaseModel, SecretStr, model_validator
from yarl import URL

DEFAULT_MEDIA_SIGNING_SECRET = "unsafe-development-only-media-signing-key"


class MediaStorageConfig(BaseModel):
    backend: Literal["local", "s3"] = "local"
    endpoint_url: str = ""
    region: str = ""
    bucket: str = ""
    access_key_id: str = ""
    secret_access_key: SecretStr = SecretStr("")
    read_only_secret_access_key: SecretStr = SecretStr("")
    object_prefix: str = "ads"
    public_path: str = "/media"
    signing_secret: SecretStr = SecretStr(DEFAULT_MEDIA_SIGNING_SECRET)
    signed_url_ttl_seconds: int = 30 * 24 * 60 * 60
    upload_concurrency: int = 4
    multipart_threshold_mb: int = 100
    multipart_chunk_mb: int = 16
    multipart_concurrency: int = 2

    @model_validator(mode="after")
    def validate_storage(self) -> "MediaStorageConfig":
        if (
            self.public_path == "/"
            or "//" in self.public_path
            or re.fullmatch(r"/[A-Za-z0-9/_-]+", self.public_path) is None
        ):
            raise ValueError("media public_path must be an absolute URL path")
        if (
            re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._/-]*", self.object_prefix) is None
            or "//" in self.object_prefix
            or any(part in {"", ".", ".."} for part in self.object_prefix.split("/"))
        ):
            raise ValueError("media object_prefix must be a safe object path")
        if not 60 <= self.signed_url_ttl_seconds <= 31 * 24 * 60 * 60:
            raise ValueError(
                "media signed URL TTL must be between 60 seconds and 31 days"
            )
        if not 1 <= self.upload_concurrency <= 32:
            raise ValueError("media upload_concurrency must be between 1 and 32")
        if self.multipart_threshold_mb < 5 or self.multipart_chunk_mb < 5:
            raise ValueError("media multipart sizes must be at least 5 MB")
        if not 1 <= self.multipart_concurrency <= 16:
            raise ValueError("media multipart_concurrency must be between 1 and 16")
        if self.backend == "s3":
            required = {
                "endpoint_url": self.endpoint_url,
                "region": self.region,
                "bucket": self.bucket,
                "access_key_id": self.access_key_id,
                "secret_access_key": self.secret_access_key.get_secret_value(),
            }
            missing = [name for name, value in required.items() if not value]
            if missing:
                raise ValueError(f"missing S3 settings: {', '.join(missing)}")
            endpoint = URL(self.endpoint_url)
            if (
                endpoint.scheme != "https"
                or not endpoint.host
                or endpoint.user is not None
                or endpoint.password is not None
                or endpoint.query_string
                or endpoint.fragment
                or endpoint.path not in {"", "/"}
            ):
                raise ValueError(
                    "S3 endpoint_url must be an HTTPS origin without credentials, "
                    "path, query, or fragment"
                )
            if re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]{1,62}", self.bucket) is None:
                raise ValueError("media bucket must be a valid S3 bucket name")
            if re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]*", self.region) is None:
                raise ValueError("media region must contain only safe characters")
        return self

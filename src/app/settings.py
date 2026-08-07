import re
import sys
from functools import lru_cache
from pathlib import Path
from typing import Literal, final

from pydantic import BaseModel, SecretStr, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict
from yarl import URL


class PlaywrightConfig(BaseModel):
    enabled: bool = False
    headless: bool = True
    max_browsers: int = 2
    contexts_per_browser: int = 5
    browser_args: list[str] = [
        "--disable-blink-features=AutomationControlled",
        "--disable-dev-shm-usage",
        "--no-sandbox",
    ]


class ViewportConfig(BaseModel):
    width_min: int = 1280
    width_max: int = 1920
    height_min: int = 800
    height_max: int = 1080


class UserAgentConfig(BaseModel):
    browsers: list[str] = ["Chrome", "Edge"]
    fallback: str = (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/131.0.0.0 Safari/537.36"
    )


class PostgresConfig(BaseModel):
    user: str = "postgres"
    password: str = "postgres"
    host: str = "localhost"
    port: int = 5432
    db: str = "app"


class RedisConfig(BaseModel):
    host: str = "localhost"
    port: int = 6379
    db: int = 0


DEFAULT_JWT_SECRET = "change-me-in-production"


class JwtConfig(BaseModel):
    secret_key: str = DEFAULT_JWT_SECRET
    algorithm: str = "HS256"
    access_token_expires_in_minutes: int = 30
    refresh_expires_in_minutes: int = 1440  # 1 day


class APIConfig(BaseModel):
    title: str = "FB Spy API"
    version: str = "1.0.0"
    port: int = 8000
    host: str = "0.0.0.0"
    allowed_hosts: list[str] = ["*"]

    page_max_size: int = 100
    page_default_size: int = 10


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


class FacebookConfig(BaseModel):
    data_dir: Path = Path("storage/facebook")
    runner_out_dir: Path = Path("storage/facebook/runs")
    runner_module: str = "app.services.facebook_runner"
    runner_python: str = sys.executable
    octo_host: str = "127.0.0.1"
    octo_port: int = 58888
    octo_profile_uuid: str = "replace-with-octo-profile-uuid"
    octo_headless: bool = False
    octo_api_token: str = ""
    octo_search_tags: str = ""
    default_minutes: float = 10.0
    default_resolve_max: int = 200
    default_collect_scrolls: int = 10000
    default_scroll_px: int = 520
    default_country: str | None = "Turkey"
    media_mount_path: str = "/media"
    relevance_filter_enabled: bool = False
    relevance_filter_concurrency: int = 4
    relevance_filter_taskiq_enabled: bool = True
    relevance_filter_task_timeout_seconds: float = 45.0
    relevance_filter_task_retries: int = 1
    streaming_import_enabled: bool = True
    streaming_import_poll_seconds: float = 1.0
    landing_archive_enabled: bool = True
    landing_archive_timeout_seconds: float = 20.0
    landing_archive_max_resources: int = 120
    video_recording_enabled: bool = True
    video_recording_max_seconds: float = 30.0
    video_recording_fps: int = 8


class GeminiConfig(BaseModel):
    api_key: str = ""
    model: str = "gemini-2.5-flash"


class PathsConfig:
    src_path = Path(__file__).parent.parent
    app_path = src_path / "app"
    database_path = app_path / "database"
    models_path = database_path / "models"
    modules_path = app_path / "api" / "modules"


@final
class Config(BaseSettings):
    model_config: SettingsConfigDict = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        env_prefix="APP__",
        env_nested_delimiter="__",
        extra="ignore",
    )

    env: Literal["local", "dev", "prod"] = "local"

    api: APIConfig = APIConfig()
    jwt: JwtConfig = JwtConfig()
    media: MediaStorageConfig = MediaStorageConfig()

    postgres: PostgresConfig = PostgresConfig()
    redis: RedisConfig = RedisConfig()

    playwright: PlaywrightConfig = PlaywrightConfig()
    viewport: ViewportConfig = ViewportConfig()
    useragent: UserAgentConfig = UserAgentConfig()
    facebook: FacebookConfig = FacebookConfig()
    gemini: GeminiConfig = GeminiConfig()

    paths: PathsConfig = PathsConfig()

    @model_validator(mode="after")
    def validate_secrets(self) -> "Config":
        signing_secret = self.media.signing_secret.get_secret_value()
        if len(signing_secret) < 32:
            raise ValueError("media signing_secret must contain at least 32 characters")
        if self.env == "prod" and (
            self.jwt.secret_key == DEFAULT_JWT_SECRET
            or len(self.jwt.secret_key.encode("utf-8")) < 32
        ):
            raise ValueError(
                "jwt secret_key must be changed and contain at least 32 bytes in production"
            )
        if self.env == "prod" and signing_secret == DEFAULT_MEDIA_SIGNING_SECRET:
            raise ValueError("media signing_secret must be changed in production")
        if (
            self.media.backend == "s3"
            and signing_secret == self.media.secret_access_key.get_secret_value()
        ):
            raise ValueError("media signing_secret must differ from the S3 secret")
        if self.env == "prod" and self.media.backend == "s3":
            write_secret = self.media.secret_access_key.get_secret_value()
            read_secret = self.media.read_only_secret_access_key.get_secret_value()
            if not read_secret:
                raise ValueError(
                    "media read_only_secret_access_key is required in production"
                )
            if read_secret == write_secret:
                raise ValueError(
                    "media read-only S3 secret must differ from the write secret"
                )
            if read_secret == signing_secret:
                raise ValueError(
                    "media signing_secret must differ from the read-only S3 secret"
                )
        return self

    @property
    def database_url(self) -> str:
        host = "localhost" if self.env == "local" else self.postgres.host
        return URL.build(
            scheme="postgresql+asyncpg",
            user=self.postgres.user,
            password=self.postgres.password,
            host=host,
            port=self.postgres.port,
            path=f"/{self.postgres.db}",
        ).human_repr()

    @property
    def redis_url(self) -> str:
        host = "localhost" if self.env == "local" else self.redis.host
        return URL.build(
            scheme="redis",
            host=host,
            port=self.redis.port,
            path=f"/{self.redis.db}",
        ).human_repr()


@lru_cache
def get_config() -> Config:
    return Config()

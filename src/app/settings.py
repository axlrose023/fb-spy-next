from functools import lru_cache
from pathlib import Path
from typing import Literal, final

from pydantic import model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict
from yarl import URL

from app.accounts.settings import DEFAULT_JWT_SECRET, JwtConfig
from app.ad_library.media.settings import (
    DEFAULT_MEDIA_SIGNING_SECRET,
    MediaStorageConfig,
)
from app.api.settings import APIConfig
from app.browser.settings import PlaywrightConfig, UserAgentConfig, ViewportConfig
from app.clients.settings import GeminiConfig
from app.database.settings import PostgresConfig, RedisConfig
from app.facebook.settings import FacebookConfig


class PathsConfig:
    src_path = Path(__file__).parent.parent
    app_path = src_path / "app"
    database_path = app_path / "database"
    models_path = database_path / "models"
    modules_path = app_path / "api" / "modules"


@final
class Config(BaseSettings):
    model_config = SettingsConfigDict(
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

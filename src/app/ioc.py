from collections.abc import AsyncIterator
from datetime import timedelta

from dishka import AsyncContainer, Provider, Scope, make_async_container, provide
from sqlalchemy.ext.asyncio import AsyncSession

from app.accounts.auth import AuthService
from app.accounts.auth.adapters import (
    AccountUserReader,
    BcryptPasswordVerifier,
    JwtTokenCodec,
)
from app.accounts.users import UserService
from app.accounts.users.adapters.persistence import SqlAlchemyUserRepository
from app.ad_library.ads import AdService
from app.ad_library.ads.adapters.persistence import FacebookAd, SqlAlchemyAdRepository
from app.ad_library.media import MediaService, MediaStorage, MediaURLSigner
from app.ad_library.media.adapters.ads import AdMediaReader
from app.ad_library.media.configuration import configured_signer, configured_storage
from app.ad_library.statistics import StatisticsService
from app.ad_library.statistics.adapters import SqlAlchemyAdStatisticsReader
from app.clients.providers import HttpClientsProvider
from app.database.ioc import DatabaseProvider
from app.database.uow import UnitOfWork
from app.facebook.runs import RunDefaults, RunService
from app.facebook.runs.adapters import (
    LegacyRunAdsImporter,
    RunArtifactDirectoryStager,
)
from app.facebook.runs.adapters.persistence import (
    SqlAlchemyRunRepository,
    SqlAlchemyRunTransaction,
)
from app.facebook.runs.adapters.processes import FacebookRunnerRegistry
from app.services.facebook.importer import FacebookAdsImporter
from app.settings import Config, get_config

try:
    from app.services.browser import BrowserPool, ContextFactory, UserAgentProvider
except ModuleNotFoundError:
    _BROWSER_PROVIDER_ENABLED = False
else:
    _BROWSER_PROVIDER_ENABLED = True


class AppProvider(Provider):
    @provide(scope=Scope.APP)
    def get_config(self) -> Config:
        return get_config()


class ServicesProvider(Provider):
    @provide(scope=Scope.APP)
    def get_media_signer(self, config: Config) -> MediaURLSigner:
        return configured_signer(config)

    @provide(scope=Scope.APP)
    def get_media_storage(self, config: Config) -> MediaStorage:
        return configured_storage(config)

    @provide(scope=Scope.APP)
    def get_jwt_token_codec(self, config: Config) -> JwtTokenCodec:
        return JwtTokenCodec(
            secret_key=config.jwt.secret_key,
            algorithm=config.jwt.algorithm,
            access_ttl=timedelta(
                minutes=config.jwt.access_token_expires_in_minutes
            ),
            refresh_ttl=timedelta(minutes=config.jwt.refresh_expires_in_minutes),
        )

    @provide(scope=Scope.APP)
    def get_password_verifier(self) -> BcryptPasswordVerifier:
        return BcryptPasswordVerifier()

    @provide(scope=Scope.REQUEST)
    def get_user_repository(
        self,
        session: AsyncSession,
    ) -> SqlAlchemyUserRepository:
        return SqlAlchemyUserRepository(session)

    @provide(scope=Scope.REQUEST)
    def get_ad_repository(
        self,
        session: AsyncSession,
    ) -> SqlAlchemyAdRepository:
        return SqlAlchemyAdRepository(session)

    @provide(scope=Scope.REQUEST)
    def get_auth_service(
        self,
        users: SqlAlchemyUserRepository,
        token_codec: JwtTokenCodec,
        password_verifier: BcryptPasswordVerifier,
    ) -> AuthService:
        return AuthService(
            AccountUserReader(users),
            token_codec,
            password_verifier,
        )

    @provide(scope=Scope.REQUEST)
    def get_user_service(
        self,
        users: SqlAlchemyUserRepository,
        password_verifier: BcryptPasswordVerifier,
    ) -> UserService:
        return UserService(users, password_verifier)

    @provide(scope=Scope.REQUEST)
    def get_media_service(
        self,
        ads: SqlAlchemyAdRepository,
        media_storage: MediaStorage,
        media_signer: MediaURLSigner,
    ) -> MediaService:
        return MediaService(
            AdMediaReader(ads),
            media_storage,
            media_signer,
        )

    @provide(scope=Scope.APP)
    def get_facebook_ads_importer(
        self,
        config: Config,
        media_storage: MediaStorage,
    ) -> FacebookAdsImporter:
        return FacebookAdsImporter(config, media_storage)

    @provide(scope=Scope.APP)
    def get_facebook_runner_registry(
        self,
        config: Config,
        importer: FacebookAdsImporter,
    ) -> FacebookRunnerRegistry:
        return FacebookRunnerRegistry(config, importer)

    @provide(scope=Scope.REQUEST)
    async def get_ad_service(
        self,
        ads: SqlAlchemyAdRepository,
        media_signer: MediaURLSigner,
    ) -> AdService:
        return AdService(ads, media_signer)

    @provide(scope=Scope.REQUEST)
    def get_run_service(
        self,
        session: AsyncSession,
        uow: UnitOfWork,
        config: Config,
        importer: FacebookAdsImporter,
        runner_registry: FacebookRunnerRegistry,
    ) -> RunService:
        facebook = config.facebook
        return RunService(
            SqlAlchemyRunRepository(session),
            SqlAlchemyRunTransaction(session),
            runner_registry,
            LegacyRunAdsImporter(uow, importer),
            RunArtifactDirectoryStager(facebook.data_dir),
            RunDefaults(
                minutes=facebook.default_minutes,
                collect_scrolls=facebook.default_collect_scrolls,
                resolve_max=facebook.default_resolve_max,
                scroll_px=facebook.default_scroll_px,
                octo_profile_uuid=facebook.octo_profile_uuid,
            ),
        )

    @provide(scope=Scope.REQUEST)
    def get_statistics_reader(
        self,
        session: AsyncSession,
    ) -> SqlAlchemyAdStatisticsReader:
        return SqlAlchemyAdStatisticsReader(session, FacebookAd)

    @provide(scope=Scope.REQUEST)
    def get_stats_service(
        self,
        reader: SqlAlchemyAdStatisticsReader,
    ) -> StatisticsService:
        return StatisticsService(reader)


if _BROWSER_PROVIDER_ENABLED:
    class BrowserProvider(Provider):
        @provide(scope=Scope.APP)
        def get_user_agent_provider(self, config: Config) -> UserAgentProvider:
            return UserAgentProvider(config.useragent)

        @provide(scope=Scope.APP)
        def get_context_factory(
            self,
            user_agent_provider: UserAgentProvider,
            config: Config,
        ) -> ContextFactory:
            return ContextFactory(user_agent_provider, config.viewport)

        @provide(scope=Scope.APP)
        async def get_browser_pool(self, config: Config) -> AsyncIterator[BrowserPool]:
            pool = BrowserPool(config=config.playwright)
            await pool.start()
            yield pool
            await pool.stop()


def get_async_container() -> AsyncContainer:
    providers: list[Provider] = [
        AppProvider(),
        DatabaseProvider(),
        ServicesProvider(),
        HttpClientsProvider(),
    ]
    if _BROWSER_PROVIDER_ENABLED and get_config().playwright.enabled:
        providers.append(BrowserProvider())
    return make_async_container(*providers)

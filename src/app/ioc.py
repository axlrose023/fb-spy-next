from collections.abc import AsyncIterator

from dishka import AsyncContainer, Provider, Scope, make_async_container, provide
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.modules.ads.service import FacebookAdService
from app.api.modules.auth.service import AuthService
from app.api.modules.auth.services import JwtService
from app.api.modules.runs.service import FacebookRunService
from app.api.modules.stats.service import StatsService
from app.api.modules.users.service import UserService
from app.clients.providers import HttpClientsProvider
from app.database.engine import SessionFactory
from app.database.uow import UnitOfWork
from app.services.facebook import FacebookAdsImporter, FacebookRunnerRegistry
from app.services.media_storage import MediaStorage, MediaURLSigner
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

    @provide(scope=Scope.REQUEST)
    async def get_session(self) -> AsyncIterator[AsyncSession]:
        async with SessionFactory() as session:
            yield session

    @provide(scope=Scope.REQUEST)
    async def get_uow(self, session: AsyncSession) -> AsyncIterator[UnitOfWork]:
        async with UnitOfWork(session) as uow:
            yield uow


class ServicesProvider(Provider):
    @provide(scope=Scope.APP)
    def get_media_signer(self, config: Config) -> MediaURLSigner:
        return MediaURLSigner(config)

    @provide(scope=Scope.APP)
    def get_media_storage(self, config: Config) -> MediaStorage:
        return MediaStorage(config)

    @provide(scope=Scope.APP)
    def get_jwt_service(self, config: Config) -> JwtService:
        return JwtService(config)

    @provide(scope=Scope.REQUEST)
    async def get_auth_service(
        self, uow: UnitOfWork, jwt_service: JwtService
    ) -> AuthService:
        return AuthService(uow, jwt_service)

    @provide(scope=Scope.REQUEST)
    async def get_user_service(
        self, uow: UnitOfWork, auth_service: AuthService
    ) -> UserService:
        return UserService(uow, auth_service)

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
    async def get_facebook_ad_service(
        self,
        uow: UnitOfWork,
        media_signer: MediaURLSigner,
        media_storage: MediaStorage,
    ) -> FacebookAdService:
        return FacebookAdService(uow, media_signer, media_storage)

    @provide(scope=Scope.REQUEST)
    async def get_facebook_run_service(
        self,
        uow: UnitOfWork,
        config: Config,
        importer: FacebookAdsImporter,
        runner_registry: FacebookRunnerRegistry,
    ) -> FacebookRunService:
        return FacebookRunService(uow, config, importer, runner_registry)

    @provide(scope=Scope.REQUEST)
    async def get_stats_service(self, uow: UnitOfWork) -> StatsService:
        return StatsService(uow)


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
        ServicesProvider(),
        HttpClientsProvider(),
    ]
    if _BROWSER_PROVIDER_ENABLED and get_config().playwright.enabled:
        providers.append(BrowserProvider())
    return make_async_container(*providers)

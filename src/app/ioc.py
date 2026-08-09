from collections.abc import AsyncIterator

from dishka import AsyncContainer, Provider, Scope, make_async_container, provide
from sqlalchemy.ext.asyncio import AsyncSession

from app.accounts.ioc import AccountsProvider
from app.ad_library.ioc import AdLibraryProvider
from app.ad_library.media import MediaStorage
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
        AccountsProvider(),
        AdLibraryProvider(),
        ServicesProvider(),
        HttpClientsProvider(),
    ]
    if _BROWSER_PROVIDER_ENABLED and get_config().playwright.enabled:
        providers.append(BrowserProvider())
    return make_async_container(*providers)

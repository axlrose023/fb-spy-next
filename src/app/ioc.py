from collections.abc import AsyncIterator

from dishka import AsyncContainer, Provider, Scope, make_async_container, provide

from app.accounts.ioc import AccountsProvider
from app.ad_library.ioc import AdLibraryProvider
from app.clients.providers import HttpClientsProvider
from app.database.ioc import DatabaseProvider
from app.facebook.ioc import FacebookProvider
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
        FacebookProvider(),
        HttpClientsProvider(),
    ]
    if _BROWSER_PROVIDER_ENABLED and get_config().playwright.enabled:
        providers.append(BrowserProvider())
    return make_async_container(*providers)

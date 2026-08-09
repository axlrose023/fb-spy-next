from dishka import AsyncContainer, Provider, Scope, make_async_container, provide

from app.accounts.ioc import AccountsProvider
from app.ad_library.ioc import AdLibraryProvider
from app.browser import browser_provider
from app.clients.providers import HttpClientsProvider
from app.database.ioc import DatabaseProvider
from app.facebook.ioc import FacebookProvider
from app.settings import Config, get_config


class AppProvider(Provider):
    @provide(scope=Scope.APP)
    def get_config(self) -> Config:
        return get_config()


def get_async_container() -> AsyncContainer:
    providers: list[Provider] = [
        AppProvider(),
        DatabaseProvider(),
        AccountsProvider(),
        AdLibraryProvider(),
        FacebookProvider(),
        HttpClientsProvider(),
    ]
    optional_browser_provider = browser_provider()
    if optional_browser_provider is not None and get_config().playwright.enabled:
        providers.append(optional_browser_provider)
    return make_async_container(*providers)

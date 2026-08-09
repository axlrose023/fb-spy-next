from __future__ import annotations

from collections.abc import AsyncIterator, Callable

from dishka import Provider, Scope, provide

from app.settings import Config

try:
    from .context import ContextFactory
    from .pool import BrowserPool
    from .useragent import UserAgentProvider
except ModuleNotFoundError:
    _BROWSER_PROVIDER_ENABLED = False
else:
    _BROWSER_PROVIDER_ENABLED = True

_browser_provider_factory: Callable[[], Provider] | None = None

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
        async def get_browser_pool(
            self,
            config: Config,
        ) -> AsyncIterator[BrowserPool]:
            pool = BrowserPool(config=config.playwright)
            await pool.start()
            yield pool
            await pool.stop()

    _browser_provider_factory = BrowserProvider


def browser_provider_available() -> bool:
    return _BROWSER_PROVIDER_ENABLED


def browser_provider() -> Provider | None:
    if not _BROWSER_PROVIDER_ENABLED:
        return None
    factory = _browser_provider_factory
    return None if factory is None else factory()

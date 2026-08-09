from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from .context import ContextFactory
    from .ioc import browser_provider, browser_provider_available
    from .pool import BrowserPool
    from .useragent import UserAgentProvider

_EXPORTS = {
    "BrowserPool": ("pool", "BrowserPool"),
    "ContextFactory": ("context", "ContextFactory"),
    "UserAgentProvider": ("useragent", "UserAgentProvider"),
    "browser_provider": ("ioc", "browser_provider"),
    "browser_provider_available": ("ioc", "browser_provider_available"),
}

__all__ = list(_EXPORTS)


def __getattr__(name: str) -> Any:
    target = _EXPORTS.get(name)
    if target is None:
        raise AttributeError(name)
    module_name, attribute = target
    module = __import__(f"{__name__}.{module_name}", fromlist=[attribute])
    value = getattr(module, attribute)
    globals()[name] = value
    return value

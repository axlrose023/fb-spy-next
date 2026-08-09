from __future__ import annotations

import logging
import random
from typing import Any, cast

from playwright.async_api import Browser, BrowserContext

from app.settings import get_config

from .settings import ViewportConfig
from .useragent import UserAgentProvider

logger = logging.getLogger("app.services.browser.context")


class ContextFactory:
    def __init__(
        self,
        user_agent_provider: UserAgentProvider | None = None,
        viewport_config: ViewportConfig | None = None,
    ) -> None:
        self._ua_provider = user_agent_provider or UserAgentProvider()
        self._viewport = viewport_config or get_config().viewport

    def _random_viewport(self) -> dict[str, int]:
        return {
            "width": random.randint(self._viewport.width_min, self._viewport.width_max),
            "height": random.randint(
                self._viewport.height_min,
                self._viewport.height_max,
            ),
        }

    async def create(
        self,
        browser: Browser,
    ) -> tuple[BrowserContext, dict[str, Any]]:
        viewport = self._random_viewport()
        user_agent = self._ua_provider.get()

        context = await browser.new_context(
            viewport=cast(Any, viewport),
            user_agent=user_agent,
        )
        metadata = {
            "user_agent": user_agent,
            "viewport": viewport,
        }
        return context, metadata

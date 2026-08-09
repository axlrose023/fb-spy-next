from __future__ import annotations

import logging

from fake_useragent import UserAgent

from app.settings import get_config

from .settings import UserAgentConfig

logger = logging.getLogger("app.services.browser.useragent")


class UserAgentProvider:
    def __init__(self, config: UserAgentConfig | None = None) -> None:
        self._config = config or get_config().useragent
        try:
            self._ua: UserAgent | None = UserAgent(browsers=self._config.browsers)
        except Exception as exc:
            logger.warning("Failed to initialize UserAgent: %s", exc)
            self._ua = None

    def get(self) -> str:
        if self._ua:
            try:
                user_agent: str = self._ua.random
                return user_agent
            except Exception:
                pass
        fallback: str = self._config.fallback
        return fallback

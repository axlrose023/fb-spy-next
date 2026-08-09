"""Compatibility facade for the modular Facebook relevance application."""

from __future__ import annotations

from typing import Any

from app.facebook.relevance import (
    RelevanceClassificationService,
    RelevanceResult,
    RelevanceService,
    apply_prefilter_uncertainty_guard,
    apply_scope_guards,
    parse_model_json,
)
from app.facebook.relevance.adapters import GeminiRelevanceProvider
from app.facebook.relevance.classification.matching import contains_term
from app.facebook.relevance.classification.prompt import (
    PREFILTER_TEXT_PROMPT,
    PREFILTER_VISION_PROMPT,
    TEXT_PROMPT,
    VISION_PROMPT,
)
from app.settings import Config

_contains_term = contains_term


class FacebookAdRelevanceFilter(RelevanceService):
    """Deprecated name retained while legacy consumers move to RelevanceService."""

    def __init__(
        self,
        gemini: Any | None,
        *,
        enabled: bool,
        concurrency: int = 3,
    ) -> None:
        super().__init__(
            RelevanceClassificationService(gemini, enabled=enabled),
            concurrency=concurrency,
        )

    @classmethod
    def from_config(cls, config: Config) -> FacebookAdRelevanceFilter:
        enabled = config.facebook.relevance_filter_enabled
        provider = (
            GeminiRelevanceProvider(config.gemini.api_key, config.gemini.model)
            if enabled and config.gemini.api_key
            else None
        )
        return cls(
            provider,
            enabled=enabled and provider is not None,
            concurrency=config.facebook.relevance_filter_concurrency,
        )

__all__ = [
    "FacebookAdRelevanceFilter",
    "PREFILTER_TEXT_PROMPT",
    "PREFILTER_VISION_PROMPT",
    "RelevanceResult",
    "TEXT_PROMPT",
    "VISION_PROMPT",
    "apply_prefilter_uncertainty_guard",
    "apply_scope_guards",
    "parse_model_json",
]

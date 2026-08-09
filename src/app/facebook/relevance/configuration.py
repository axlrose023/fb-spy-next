from __future__ import annotations

from typing import Any

from .adapters import GeminiRelevanceProvider
from .classification import RelevanceClassificationService
from .service import RelevanceService


def configured_relevance_service(config: Any) -> RelevanceService:
    enabled = bool(config.facebook.relevance_filter_enabled)
    api_key = str(config.gemini.api_key or "")
    provider = (
        GeminiRelevanceProvider(api_key, config.gemini.model)
        if enabled and api_key
        else None
    )
    classifier = RelevanceClassificationService(
        provider,
        enabled=enabled and provider is not None,
    )
    return RelevanceService(
        classifier,
        concurrency=config.facebook.relevance_filter_concurrency,
    )

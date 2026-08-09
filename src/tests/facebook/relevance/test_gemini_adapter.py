import asyncio
from types import SimpleNamespace

import pytest

from app.facebook.relevance import (
    RelevanceProviderError,
    RelevanceProviderRateLimited,
    RelevanceProviderTimeout,
)
from app.facebook.relevance.adapters import gemini

pytestmark = pytest.mark.contract


class _Models:
    def __init__(self, outcome) -> None:
        self.outcome = outcome

    async def generate_content(self, **_kwargs):
        if isinstance(self.outcome, BaseException):
            raise self.outcome
        if self.outcome == "hang":
            await asyncio.sleep(60)
        return SimpleNamespace(text=self.outcome)


def _provider(monkeypatch: pytest.MonkeyPatch, outcome):
    client = SimpleNamespace(
        aio=SimpleNamespace(
            models=_Models(outcome),
            files=SimpleNamespace(),
        )
    )
    monkeypatch.setattr(gemini.genai, "Client", lambda **_kwargs: client)
    return gemini.GeminiRelevanceProvider("redacted", "test-model")


@pytest.mark.asyncio
async def test_provider_maps_rate_limit_without_leaking_response(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    provider = _provider(monkeypatch, RuntimeError("429 secret request payload"))

    with pytest.raises(RelevanceProviderRateLimited) as error:
        await provider.generate_from_text("prompt")

    assert "secret" not in str(error.value)
    assert error.value.__cause__ is None


@pytest.mark.asyncio
async def test_provider_maps_timeout(monkeypatch: pytest.MonkeyPatch) -> None:
    provider = _provider(monkeypatch, "hang")
    monkeypatch.setattr(gemini, "_GENERATE_TIMEOUT_S", 0.001)

    with pytest.raises(RelevanceProviderTimeout):
        await provider.generate_from_text("prompt")


@pytest.mark.asyncio
async def test_provider_maps_unknown_failure(monkeypatch: pytest.MonkeyPatch) -> None:
    provider = _provider(monkeypatch, RuntimeError("provider exploded"))

    with pytest.raises(RelevanceProviderError):
        await provider.generate_from_text("prompt")

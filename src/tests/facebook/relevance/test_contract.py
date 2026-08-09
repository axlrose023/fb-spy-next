from pathlib import Path

import pytest

from app.facebook.relevance import (
    RelevanceClassificationService,
    RelevanceDecision,
    RelevanceGate,
    RelevanceService,
    gate_for,
    parse_model_json,
)

pytestmark = pytest.mark.unit


@pytest.mark.parametrize(
    ("response", "decision"),
    [
        ('{"result":"relevant","reason":"evidence"}', "relevant"),
        ('{"result":"uncertain","reason":"inspect landing"}', "not_relevant"),
        ('{"result":"unknown"}', "not_relevant"),
        ("not json", "not_relevant"),
        ("[]", "not_relevant"),
        ("", "not_relevant"),
    ],
)
def test_parser_is_fail_closed(response: str, decision: str) -> None:
    assert parse_model_json(response)["result"] == decision


def test_uncertain_requires_explicit_prefilter_contract() -> None:
    result = parse_model_json(
        '{"result":"uncertain","reason":"inspect landing"}',
        allowed_results={"relevant", "not_relevant", "uncertain"},
    )

    assert result["result"] == "uncertain"
    assert gate_for(result["result"]) is RelevanceGate.HOLD


@pytest.mark.asyncio
async def test_disabled_service_preserves_legacy_passthrough(tmp_path: Path) -> None:
    service = RelevanceService(
        RelevanceClassificationService(None, enabled=False),
    )

    result = await service.analyze_raw_ad({"advertiser": "Any"}, tmp_path)

    assert result.relevant is True
    assert result.decision is RelevanceDecision.RELEVANT
    assert result.source == "disabled"

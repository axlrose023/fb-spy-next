from pathlib import Path
from types import SimpleNamespace

import pytest

from app.facebook.relevance.classification import command
from app.facebook.relevance.models import RelevanceResult

pytestmark = pytest.mark.unit


class _Relevance:
    enabled = True

    async def analyze_raw_ad(
        self,
        raw,
        _run_dir,
        *,
        prefilter: bool = False,
    ):
        result = "uncertain" if prefilter and raw.get("hold") else "relevant"
        return RelevanceResult(
            result == "relevant",
            {"result": result, "reason": "fixture"},
            source="metadata",
        )


def _config() -> SimpleNamespace:
    return SimpleNamespace(
        facebook=SimpleNamespace(relevance_filter_concurrency=2),
    )


def test_prefilter_command_writes_gate_artifacts(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = tmp_path / "ads.json"
    source.write_text('[{"advertiser":"A"},{"hold":true}]', encoding="utf-8")
    monkeypatch.setattr(command, "configured_relevance_service", lambda _config: _Relevance())

    status = command.run_prefilter(SimpleNamespace(), tmp_path, source, _config())

    assert status == 0
    candidates = command.load_ads(tmp_path / "ads.candidates.json")
    held = command.load_ads(tmp_path / "ads.prefilter.json")
    assert len(candidates) == 1
    assert [item["relevance_gate"] for item in held] == ["allow", "hold"]


def test_standard_command_uses_complete_cache_before_provider(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = tmp_path / "ads.json"
    source.write_text('[{"advertiser":"A"}]', encoding="utf-8")
    (tmp_path / "ads.classified.json").write_text(
        '[{"relevance":{"result":"relevant"}}]',
        encoding="utf-8",
    )
    monkeypatch.setattr(
        command,
        "configured_relevance_service",
        lambda _config: pytest.fail("provider must not be constructed for cached run"),
    )
    args = SimpleNamespace(force=False, include_video=False)

    assert command.run_standard(args, tmp_path, source, _config()) == 0


def test_finalize_never_reclassifies_denied_row(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = tmp_path / "ads.enriched.json"
    source.write_text(
        '[{"relevance_gate":"deny","prefilter_relevance":'
        '{"result":"not_relevant","reason":"shop"}}]',
        encoding="utf-8",
    )
    monkeypatch.setattr(command, "configured_relevance_service", lambda _config: _Relevance())

    status = command.run_finalize(
        SimpleNamespace(include_video=False),
        tmp_path,
        source,
        _config(),
    )

    assert status == 0
    rows = command.load_ads(tmp_path / "ads.classified.json")
    assert rows[0]["relevance"]["result"] == "not_relevant"

import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from app.facebook.enrichment.adapters.playwright import runtime
from app.facebook.enrichment.service import EnrichmentService

pytestmark = pytest.mark.unit


def test_no_allowed_candidates_never_configures_or_opens_profile(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    source = tmp_path / "ads.prefilter.json"
    source.write_text('[{"relevance_gate":"deny"}]', encoding="utf-8")
    monkeypatch.setattr(
        runtime,
        "acquire_command_session",
        lambda **_kwargs: pytest.fail("profile must stay untouched"),
    )
    args = SimpleNamespace(run_dir=tmp_path, source=None, output=None)

    code = runtime.run(args, stop_requested=lambda: False)

    assert code == 0
    assert (tmp_path / "ads.enriched.json").exists()
    assert not (tmp_path / "enrichment_events.jsonl").exists()


def test_finished_event_keeps_infrastructure_error(tmp_path: Path) -> None:
    paths = {
        "output": tmp_path / "ads.enriched.json",
        "summary": tmp_path / "enrichment_summary.json",
        "events": tmp_path / "enrichment_events.jsonl",
    }

    summary = runtime._write_completed(
        paths,
        [],
        EnrichmentService(clock=lambda: "now"),
        status="infrastructure_error",
        error="proxy failed",
    )

    event = json.loads(paths["events"].read_text(encoding="utf-8"))
    assert summary["error"] == "proxy failed"
    assert event["error"] == "proxy failed"

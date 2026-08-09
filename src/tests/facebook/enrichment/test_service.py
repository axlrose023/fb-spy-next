from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from app.facebook.enrichment import EnrichmentResult, EnrichmentService, RelevantAd
from app.facebook.enrichment.exceptions import RelevanceGateDenied

pytestmark = pytest.mark.unit


class RecordingExecutor:
    def __init__(self) -> None:
        self.calls = 0

    def enrich(
        self,
        context: Any,
        ad: RelevantAd,
        *,
        sequence: int,
        run_dir: Path,
    ) -> EnrichmentResult:
        self.calls += 1
        details = {"status": "completed", "active_actions_started": True}
        raw = {**ad.raw, "enrichment": details}
        return EnrichmentResult(raw, details)


def test_blocked_candidate_cannot_reach_executor(tmp_path: Path) -> None:
    executor = RecordingExecutor()

    with pytest.raises(RelevanceGateDenied):
        EnrichmentService().enrich_one(
            executor,
            object(),
            {"relevance_gate": "hold"},
            sequence=1,
            run_dir=tmp_path,
        )

    assert executor.calls == 0


def test_prepare_marks_non_allowed_rows_without_browser_actions() -> None:
    rows: list[dict[str, Any]] = [
        {"relevance_gate": "deny"},
        {"relevance_gate": "allow"},
        {"relevance_gate": "hold"},
    ]

    candidates = EnrichmentService().prepare(rows)

    assert candidates == [1]
    assert rows[0]["enrichment"] == {
        "status": "blocked_by_relevance_gate",
        "active_actions_started": False,
    }
    assert "enrichment" not in rows[1]
    assert rows[2]["enrichment"]["active_actions_started"] is False


def test_allowed_candidate_is_passed_as_validated_type(tmp_path: Path) -> None:
    executor = RecordingExecutor()
    raw = {"relevance_gate": "allow", "advertiser": "Relevant"}

    result = EnrichmentService().enrich_one(
        executor,
        object(),
        raw,
        sequence=2,
        run_dir=tmp_path,
    )

    assert executor.calls == 1
    assert result.ad["advertiser"] == "Relevant"


def test_summary_reports_fail_closed_invariant() -> None:
    rows = [
        {
            "relevance_gate": "deny",
            "enrichment": {"active_actions_started": True},
        },
        {
            "relevance_gate": "allow",
            "enrichment": {
                "active_actions_started": True,
                "cta_click_attempted": True,
            },
        },
    ]

    summary = EnrichmentService(clock=lambda: "now").summary(
        rows,
        status="completed",
    )

    assert summary["finished_at"] == "now"
    assert summary["active_actions_on_blocked_ads"] == 1
    assert summary["landing_click_attempts"] == 1

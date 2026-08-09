from __future__ import annotations

from pathlib import Path

import pytest

from app.facebook.orchestration import (
    CollectionPipelineHooks,
    CollectionPipelineRequest,
    CollectionPipelineService,
)

pytestmark = pytest.mark.unit


class PipelineHarness:
    def __init__(self, tmp_path: Path) -> None:
        self.tmp_path = tmp_path
        self.calls: list[str] = []
        self.existing = {
            tmp_path / "ads.json",
            tmp_path / "ads.relevant.json",
        }
        self.stopped = False
        self.stop_results: list[bool] = []
        self.enabled = True
        self.violations: list[str] = []
        self.codes: dict[str, int] = {}

    def code(self, name: str) -> int:
        self.calls.append(name)
        return self.codes.get(name, 0)

    def classifier(
        self,
        stage: str,
        source: Path | None,
        include_video: bool,
        log_name: str,
    ) -> int:
        suffix = source.name if source else "-"
        return self.code(f"classify:{stage}:{suffix}:{include_video}:{log_name}")

    def stop_requested(self) -> bool:
        if self.stop_results:
            self.stopped = self.stop_results.pop(0)
        return self.stopped

    def hooks(self) -> CollectionPipelineHooks:
        return CollectionPipelineHooks(
            run_collector=lambda: self.code("collect"),
            stop_requested=self.stop_requested,
            relevance_enabled=lambda: self.enabled,
            artifact_exists=lambda path: path in self.existing,
            audit_interest_safety=lambda: self.violations,
            record_interest_safety=lambda violations: self.calls.append(
                f"safety:{','.join(violations) or 'passed'}"
            ),
            run_classifier=self.classifier,
            run_isolated_resolver=lambda: self.code("resolve"),
            run_enricher=lambda source: self.code(f"enrich:{source.name}"),
            run_backend_import=lambda source: self.code(f"import:{source.name}"),
            record_disabled_relevance=lambda: self.calls.append("disabled"),
            log=lambda message: self.calls.append(f"log:{message}"),
        )


def request(tmp_path: Path, **overrides: bool) -> CollectionPipelineRequest:
    values = {
        "dry_run": False,
        "interest_safe_collection": True,
        "isolated_hold_resolution": True,
        "relevant_enrichment": True,
        "import_backend": True,
        "include_video": True,
        **overrides,
    }
    return CollectionPipelineRequest(collect_dir=tmp_path, **values)


def test_full_safe_pipeline_preserves_sources_and_import_order(tmp_path: Path) -> None:
    harness = PipelineHarness(tmp_path)

    pipeline = CollectionPipelineService(harness.hooks()).run(request(tmp_path))

    assert harness.calls == [
        "collect",
        "safety:passed",
        "classify:prefilter:-:False:prefilter.log",
        "resolve",
        "classify:resolve-holds:ads.isolated.json:False:gate_resolution.log",
        "enrich:ads.gated.json",
        "classify:finalize:ads.enriched.json:True:relevance.log",
        "import:ads.relevant.json",
    ]
    assert pipeline.post_collection_failed is False
    assert pipeline.relevance_code == 0


def test_safety_violation_blocks_active_pipeline_and_backend(tmp_path: Path) -> None:
    harness = PipelineHarness(tmp_path)
    harness.violations = ["nonzero_cta_click_attempts"]

    pipeline = CollectionPipelineService(harness.hooks()).run(request(tmp_path))

    assert harness.calls == [
        "collect",
        "safety:nonzero_cta_click_attempts",
        "log:interest-safety invariant failed: nonzero_cta_click_attempts",
    ]
    assert pipeline.interest_safety_code == 4
    assert pipeline.post_collection_failed is True


def test_disabled_safe_relevance_records_marker(tmp_path: Path) -> None:
    harness = PipelineHarness(tmp_path)
    harness.enabled = False

    pipeline = CollectionPipelineService(harness.hooks()).run(request(tmp_path))

    assert harness.calls == [
        "collect",
        "safety:passed",
        "disabled",
        (
            "log:safe collection has no relevance classifier; "
            "active enrichment and backend import are disabled"
        ),
    ]
    assert pipeline.relevance_code is None


def test_standard_pipeline_imports_classified_ads_and_logs_failures(
    tmp_path: Path,
) -> None:
    harness = PipelineHarness(tmp_path)
    harness.codes = {
        "classify:standard:-:False:relevance.log": 0,
        "import:ads.relevant.json": 3,
    }

    pipeline = CollectionPipelineService(harness.hooks()).run(
        request(tmp_path, interest_safe_collection=False)
    )

    assert harness.calls == [
        "collect",
        "classify:standard:-:False:relevance.log",
        "import:ads.relevant.json",
        "log:backend import code=3",
    ]
    assert pipeline.relevance_code == 0


def test_missing_classified_artifact_skips_backend_import(tmp_path: Path) -> None:
    harness = PipelineHarness(tmp_path)
    harness.existing.remove(tmp_path / "ads.relevant.json")

    pipeline = CollectionPipelineService(harness.hooks()).run(
        request(tmp_path, interest_safe_collection=False)
    )

    assert harness.calls == [
        "collect",
        "classify:standard:-:False:relevance.log",
    ]
    assert pipeline.relevance_code == 0


def test_prefilter_failure_is_reported_and_blocks_followup(tmp_path: Path) -> None:
    harness = PipelineHarness(tmp_path)
    harness.codes = {"classify:prefilter:-:False:prefilter.log": 5}

    pipeline = CollectionPipelineService(harness.hooks()).run(request(tmp_path))

    assert harness.calls[-1] == "log:relevance classifier code=5"
    assert pipeline.prefilter_code == 5
    assert pipeline.relevance_code == 5
    assert pipeline.post_collection_failed is True


def test_stop_after_prefilter_prevents_resolution_and_import(tmp_path: Path) -> None:
    harness = PipelineHarness(tmp_path)
    harness.stop_results = [False, True]

    pipeline = CollectionPipelineService(harness.hooks()).run(request(tmp_path))

    assert harness.calls == [
        "collect",
        "safety:passed",
        "classify:prefilter:-:False:prefilter.log",
    ]
    assert pipeline.prefilter_code == 0
    assert pipeline.relevance_code == 0


def test_isolated_resolution_failure_blocks_enrichment_and_import(
    tmp_path: Path,
) -> None:
    harness = PipelineHarness(tmp_path)
    harness.codes = {"resolve": 6}

    pipeline = CollectionPipelineService(harness.hooks()).run(request(tmp_path))

    assert harness.calls == [
        "collect",
        "safety:passed",
        "classify:prefilter:-:False:prefilter.log",
        "resolve",
        "log:relevance classifier code=6",
    ]
    assert pipeline.isolated_resolution_code == 6
    assert pipeline.enrichment_code == 6
    assert pipeline.relevance_code == 6


def test_gate_failure_blocks_enrichment_and_import(tmp_path: Path) -> None:
    harness = PipelineHarness(tmp_path)
    harness.codes = {
        "classify:resolve-holds:ads.isolated.json:False:gate_resolution.log": 7
    }

    pipeline = CollectionPipelineService(harness.hooks()).run(request(tmp_path))

    assert harness.calls == [
        "collect",
        "safety:passed",
        "classify:prefilter:-:False:prefilter.log",
        "resolve",
        "classify:resolve-holds:ads.isolated.json:False:gate_resolution.log",
        "log:relevance classifier code=7",
    ]
    assert pipeline.gate_resolution_code == 7
    assert pipeline.enrichment_code == 7
    assert pipeline.relevance_code == 7


def test_pipeline_can_finalize_prefilter_without_resolution_or_enrichment(
    tmp_path: Path,
) -> None:
    harness = PipelineHarness(tmp_path)

    pipeline = CollectionPipelineService(harness.hooks()).run(
        request(
            tmp_path,
            isolated_hold_resolution=False,
            relevant_enrichment=False,
        )
    )

    assert harness.calls == [
        "collect",
        "safety:passed",
        "classify:prefilter:-:False:prefilter.log",
        "classify:finalize:ads.prefilter.json:True:relevance.log",
        "import:ads.relevant.json",
    ]
    assert pipeline.isolated_resolution_code == 0
    assert pipeline.gate_resolution_code == 0
    assert pipeline.enrichment_code == 0
    assert pipeline.relevance_code == 0


def test_dry_run_skips_collector_and_active_actions(tmp_path: Path) -> None:
    harness = PipelineHarness(tmp_path)

    pipeline = CollectionPipelineService(harness.hooks()).run(
        request(tmp_path, dry_run=True)
    )

    assert harness.calls == []
    assert pipeline.collect_code == 0

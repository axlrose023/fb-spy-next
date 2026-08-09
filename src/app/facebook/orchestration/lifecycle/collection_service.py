from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from .pipeline import CollectionPipelineState

Classifier = Callable[[str, Path | None, bool, str], int]


@dataclass(frozen=True, slots=True)
class CollectionPipelineRequest:
    collect_dir: Path
    dry_run: bool
    interest_safe_collection: bool
    isolated_hold_resolution: bool
    relevant_enrichment: bool
    import_backend: bool
    include_video: bool


@dataclass(frozen=True, slots=True)
class CollectionPipelineHooks:
    run_collector: Callable[[], int]
    stop_requested: Callable[[], bool]
    relevance_enabled: Callable[[], bool]
    artifact_exists: Callable[[Path], bool]
    audit_interest_safety: Callable[[], list[str]]
    record_interest_safety: Callable[[list[str]], None]
    run_classifier: Classifier
    run_isolated_resolver: Callable[[], int]
    run_enricher: Callable[[Path], int]
    run_backend_import: Callable[[Path], int]
    record_disabled_relevance: Callable[[], None]
    log: Callable[[str], None]


class CollectionPipelineService:
    def __init__(self, hooks: CollectionPipelineHooks) -> None:
        self._hooks = hooks

    def run(self, request: CollectionPipelineRequest) -> CollectionPipelineState:
        collect_code = 0 if request.dry_run else self._hooks.run_collector()
        pipeline = CollectionPipelineState(collect_code=collect_code)
        if (
            collect_code == 0
            and request.interest_safe_collection
            and not request.dry_run
        ):
            violations = self._hooks.audit_interest_safety()
            pipeline.interest_safety_code = 4 if violations else 0
            self._hooks.record_interest_safety(violations)
            if violations:
                self._hooks.log(
                    "interest-safety invariant failed: " + ",".join(violations)
                )

        relevance_enabled = self._hooks.relevance_enabled()
        if pipeline.can_start_relevance(
            dry_run=request.dry_run,
            stop_requested=self._hooks.stop_requested(),
            relevance_enabled=relevance_enabled,
            ads_available=self._hooks.artifact_exists(request.collect_dir / "ads.json"),
        ):
            self._run_relevance_pipeline(pipeline, request)
            if pipeline.relevance_code:
                self._hooks.log(f"relevance classifier code={pipeline.relevance_code}")
        elif pipeline.should_record_disabled_relevance(
            interest_safe_collection=request.interest_safe_collection,
            dry_run=request.dry_run,
            relevance_enabled=relevance_enabled,
        ):
            self._hooks.record_disabled_relevance()
            self._hooks.log(
                "safe collection has no relevance classifier; "
                "active enrichment and backend import are disabled"
            )

        if pipeline.can_import_backend(
            import_enabled=request.import_backend,
            interest_safe_collection=request.interest_safe_collection,
            dry_run=request.dry_run,
            stop_requested=self._hooks.stop_requested(),
        ):
            import_source = (
                request.collect_dir / "ads.relevant.json"
                if pipeline.relevance_code == 0
                else request.collect_dir / "ads.json"
            )
            if self._hooks.artifact_exists(import_source):
                import_code = self._hooks.run_backend_import(import_source)
                if import_code:
                    self._hooks.log(f"backend import code={import_code}")
        return pipeline

    def _run_relevance_pipeline(
        self,
        pipeline: CollectionPipelineState,
        request: CollectionPipelineRequest,
    ) -> None:
        if not request.interest_safe_collection:
            pipeline.relevance_code = self._hooks.run_classifier(
                "standard",
                None,
                False,
                "relevance.log",
            )
            return

        pipeline.prefilter_code = self._hooks.run_classifier(
            "prefilter",
            None,
            False,
            "prefilter.log",
        )
        if pipeline.prefilter_code != 0 or self._hooks.stop_requested():
            pipeline.relevance_code = pipeline.prefilter_code
            return

        enrichment_source = request.collect_dir / "ads.prefilter.json"
        if request.isolated_hold_resolution:
            pipeline.isolated_resolution_code = self._hooks.run_isolated_resolver()
            if (
                pipeline.isolated_resolution_code == 0
                and not self._hooks.stop_requested()
            ):
                pipeline.gate_resolution_code = self._hooks.run_classifier(
                    "resolve-holds",
                    request.collect_dir / "ads.isolated.json",
                    False,
                    "gate_resolution.log",
                )
                if pipeline.gate_resolution_code == 0:
                    enrichment_source = request.collect_dir / "ads.gated.json"
        else:
            pipeline.isolated_resolution_code = 0
            pipeline.gate_resolution_code = 0

        if request.relevant_enrichment:
            if pipeline.resolution_succeeded and not self._hooks.stop_requested():
                pipeline.enrichment_code = self._hooks.run_enricher(enrichment_source)
            else:
                pipeline.enrichment_code = pipeline.resolution_failure_code
        else:
            pipeline.enrichment_code = pipeline.resolution_result_code

        if pipeline.enrichment_code == 0 and not self._hooks.stop_requested():
            finalize_source = (
                request.collect_dir / "ads.enriched.json"
                if request.relevant_enrichment
                else enrichment_source
            )
            pipeline.relevance_code = self._hooks.run_classifier(
                "finalize",
                finalize_source,
                request.include_video,
                "relevance.log",
            )
        else:
            pipeline.relevance_code = pipeline.enrichment_code

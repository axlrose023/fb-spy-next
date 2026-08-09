from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from app.facebook.profiles import Profile

from .. import (
    CollectionPipelineHooks,
    CollectionPipelineRequest,
    CollectionPipelineService,
    CollectionPipelineState,
)

Command = list[str]
CommandBuilder = Callable[[Profile, Path], Command]
ClassifierCommandBuilder = Callable[[Path, str, Path | None, bool], Command]
EnricherCommandBuilder = Callable[[Profile, Path, Path], Command]
CommandExecutor = Callable[[Command, Path, float], int]


@dataclass(frozen=True, slots=True)
class CollectionCommandRequest:
    profile: Profile
    collect_dir: Path
    dry_run: bool
    interest_safe_collection: bool
    isolated_hold_resolution: bool
    relevant_enrichment: bool
    import_backend: bool
    include_video: bool
    collector_timeout: float
    relevance_timeout: float
    isolated_resolution_timeout: float
    enrichment_timeout: float
    backend_import_timeout: float


@dataclass(frozen=True, slots=True)
class CollectionCommandHooks:
    run_command: CommandExecutor
    collector_command: CommandBuilder
    classifier_command: ClassifierCommandBuilder
    isolated_resolver_command: CommandBuilder
    enricher_command: EnricherCommandBuilder
    backend_import_command: Callable[[Profile, Path], Command]
    stop_requested: Callable[[], bool]
    relevance_enabled: Callable[[], bool]
    artifact_exists: Callable[[Path], bool]
    audit_interest_safety: Callable[[Path], list[str]]
    write_json: Callable[[Path, Any], None]
    log: Callable[[str], None]


def run_collection_command(
    request: CollectionCommandRequest,
    hooks: CollectionCommandHooks,
) -> CollectionPipelineState:
    profile = request.profile
    collect_dir = request.collect_dir
    pipeline_hooks = CollectionPipelineHooks(
        run_collector=lambda: hooks.run_command(
            hooks.collector_command(profile, collect_dir),
            collect_dir / "runner.log",
            request.collector_timeout,
        ),
        stop_requested=hooks.stop_requested,
        relevance_enabled=hooks.relevance_enabled,
        artifact_exists=hooks.artifact_exists,
        audit_interest_safety=lambda: hooks.audit_interest_safety(collect_dir),
        record_interest_safety=lambda violations: hooks.write_json(
            collect_dir / "interest_safety.json",
            {
                "status": "violation" if violations else "passed",
                "violations": violations,
            },
        ),
        run_classifier=lambda stage, source, include_video, log_name: hooks.run_command(
            hooks.classifier_command(
                collect_dir,
                stage,
                source,
                include_video,
            ),
            collect_dir / log_name,
            request.relevance_timeout,
        ),
        run_isolated_resolver=lambda: hooks.run_command(
            hooks.isolated_resolver_command(profile, collect_dir),
            collect_dir / "isolated_resolution.log",
            request.isolated_resolution_timeout,
        ),
        run_enricher=lambda source: hooks.run_command(
            hooks.enricher_command(profile, collect_dir, source),
            collect_dir / "enrichment.log",
            request.enrichment_timeout,
        ),
        run_backend_import=lambda source: hooks.run_command(
            hooks.backend_import_command(profile, source),
            collect_dir / "backend_import.log",
            request.backend_import_timeout,
        ),
        record_disabled_relevance=lambda: hooks.write_json(
            collect_dir / "relevance_summary.json",
            {
                "status": "disabled_in_interest_safe_collection",
                "total": 0,
            },
        ),
        log=lambda message: hooks.log(f"[{profile.display_name}] {message}"),
    )
    return CollectionPipelineService(pipeline_hooks).run(
        CollectionPipelineRequest(
            collect_dir=collect_dir,
            dry_run=request.dry_run,
            interest_safe_collection=request.interest_safe_collection,
            isolated_hold_resolution=request.isolated_hold_resolution,
            relevant_enrichment=request.relevant_enrichment,
            import_backend=request.import_backend,
            include_video=request.include_video,
        )
    )

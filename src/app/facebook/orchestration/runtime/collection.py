from __future__ import annotations

from pathlib import Path
from typing import Any

from app.facebook.collection import interest_safety_violations
from app.facebook.orchestration.adapters import (
    CollectionProcessCommandFactory,
    relevance_classification_enabled,
)
from app.facebook.orchestration.commands import (
    CollectionCommandHooks,
    CollectionCommandRequest,
    run_collection_command,
)
from app.facebook.orchestration.lifecycle import CollectionPipelineState
from app.facebook.profiles import Profile

from .context import RuntimeContext
from .files import load_json, write_json


def run_collection_pipeline(
    profile: Profile,
    args: Any,
    collect_dir: Path,
    context: RuntimeContext,
) -> CollectionPipelineState:
    commands = process_commands(context)
    state: CollectionPipelineState = run_collection_command(
        CollectionCommandRequest(
            profile=profile,
            collect_dir=collect_dir,
            dry_run=args.dry_run,
            interest_safe_collection=args.interest_safe_collection,
            isolated_hold_resolution=args.isolated_hold_resolution,
            relevant_enrichment=args.relevant_enrichment,
            import_backend=args.import_backend,
            include_video=not args.no_video_recording,
            collector_timeout=(args.collect_minutes * 60 + args.collect_timeout_grace),
            relevance_timeout=args.relevance_timeout,
            isolated_resolution_timeout=args.isolated_resolution_timeout,
            enrichment_timeout=args.enrichment_timeout,
            backend_import_timeout=args.backend_import_timeout,
        ),
        CollectionCommandHooks(
            run_command=lambda command, log_path, timeout: context.run_command(
                command,
                log_path,
                timeout_seconds=timeout,
            ),
            collector_command=lambda cycle_profile, run_dir: commands.collector(
                cycle_profile,
                args,
                run_dir,
            ),
            classifier_command=lambda run_dir, stage, source, include_video: (
                commands.classifier(
                    run_dir,
                    stage=stage,
                    source=source,
                    include_video=include_video,
                )
            ),
            isolated_resolver_command=lambda cycle_profile, run_dir: (
                commands.isolated_resolver(cycle_profile, args, run_dir)
            ),
            enricher_command=lambda cycle_profile, run_dir, source: commands.enricher(
                cycle_profile,
                args,
                run_dir,
                source=source,
            ),
            backend_import_command=commands.backend_import,
            stop_requested=context.stop_event.is_set,
            relevance_enabled=lambda: classification_enabled(args, context),
            artifact_exists=lambda path: path.exists(),
            audit_interest_safety=interest_safe_collection_violations,
            write_json=write_json,
            log=context.log,
        ),
    )
    return state


def interest_safe_collection_violations(run_dir: Path) -> list[str]:
    summary = load_json(run_dir / "summary.json", default={})
    ads = load_json(run_dir / "ads.json", default=None)
    violations: list[str] = interest_safety_violations(summary, ads)
    return violations


def collector_command(
    profile: Profile,
    args: Any,
    run_dir: Path,
    context: RuntimeContext,
) -> list[str]:
    command: list[str] = process_commands(context).collector(profile, args, run_dir)
    return command


def relevant_enricher_command(
    profile: Profile,
    args: Any,
    run_dir: Path,
    context: RuntimeContext,
    *,
    source: Path | None = None,
) -> list[str]:
    command: list[str] = process_commands(context).enricher(
        profile,
        args,
        run_dir,
        source=source,
    )
    return command


def backend_import_command(
    profile: Profile,
    ads_json_path: Path,
    context: RuntimeContext,
) -> list[str]:
    command: list[str] = process_commands(context).backend_import(
        profile,
        ads_json_path,
    )
    return command


def classification_enabled(args: Any, context: RuntimeContext) -> bool:
    enabled: bool = relevance_classification_enabled(
        args.classify_relevance,
        context.config.facebook,
    )
    return enabled


def process_commands(context: RuntimeContext) -> CollectionProcessCommandFactory:
    return CollectionProcessCommandFactory(context.config.facebook)

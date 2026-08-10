"""Profile-level Facebook collector orchestrator.

This is intentionally a thin CLI layer over the existing runner and calibrator.
It keeps state in JSON files, runs one job per Octo profile at a time, and does
not require backend or frontend changes.
"""

from __future__ import annotations

import json
import os
import signal
import threading
import time
from collections.abc import Sequence
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from app.facebook.adapters.octo import (
    CallbackOctoTransport,
    OctoActiveProfileSource,
    OctoHttpClient,
    OctoProfileSessionManager,
    OctoPublicProfileSource,
)
from app.facebook.calibration import (
    CalibrationIntensityPolicy,
    CalibrationPassRequest,
    CalibrationPlan,
    CalibrationProcessEnvironment,
    build_calibration_command,
    calibration_timeout_seconds,
    effective_target_goal,
    persistent_target_pool,
    plan_calibration_intensity,
)
from app.facebook.collection import interest_safety_violations
from app.facebook.orchestration import (
    CollectionPipelineState,
    OrchestrationStateStore,
    ProfileCycleSchedule,
    calibration_allows_followup,
    calibration_pass_target_cap,
    calibration_passes_for_cycle,
    calibration_targets_consumed,
    next_profile_schedule,
    recovery_evaluation_policy,
    relevance_result_meaningfully_improved,
    remaining_daily_calibration_attempts,
    remaining_profile_rest_seconds,
)
from app.facebook.orchestration import (
    RecoverySchedulePolicy as RecoverySchedulePolicy,
)
from app.facebook.orchestration.adapters import (
    FileLock,
    FileStateStore,
    OctoProcessEnvironment,
    ProcessRegistry,
    PythonProcessEnvironment,
    build_backend_import_command,
    build_collector_command,
    build_isolated_landing_resolver_command,
    build_relevance_classifier_command,
    build_relevant_enricher_command,
    octo_headless,
    octo_process_environment,
    profile_lock_path,
    python_process_environment,
    relevance_classification_enabled,
    run_orchestrator_command,
)
from app.facebook.orchestration.commands import (
    ActiveDiscoveryCommandHooks,
    CalibrationCommandHooks,
    CollectionCommandHooks,
    CollectionCommandRequest,
    CommandHandlers,
    EvaluateCommandRequest,
    MaintenanceCommandHooks,
    ProfileCycleCommandHooks,
    ProfileCycleCommandRequest,
    PublicDiscoveryCommandRequest,
    RunCommandHooks,
    RuntimeDiscoveryHooks,
    RuntimeDiscoveryRequest,
    SeedBaselineCommandRequest,
    build_parser,
    calibration_policy_from_args,
    profile_rest_seconds_from_args,
    run_active_discovery_command,
    run_calibration_command,
    run_collection_command,
    run_command,
    run_evaluate_command,
    run_profile_cycle_command,
    run_public_discovery_command,
    run_runtime_discovery,
    run_seed_baseline_command,
    schedule_policy_from_args,
)
from app.facebook.orchestration.commands import dispatch as _dispatch_command
from app.facebook.orchestration.lifecycle import (
    baseline_from_run_records,
    calibration_was_effective,
    is_healthy_relevance_result,
)
from app.facebook.profiles import Profile
from app.facebook.profiles.adapters import (
    OctoPayloadProfileSource,
    adopt_catalog_country,
    discover_catalog_profiles,
    list_catalog_profiles,
)
from app.services.facebook.health import (
    CalibrationDecision,
    CalibrationPolicy,
)
from app.settings import get_config

_PROCESS_REGISTRY = ProcessRegistry()
_STOP_EVENT = threading.Event()
ProfileConfig = Profile


StateStore = FileStateStore
_build_parser = build_parser
_baseline_from_run_records = baseline_from_run_records
_calibration_was_effective = calibration_was_effective
_is_healthy_relevance_result = is_healthy_relevance_result
_next_profile_schedule = next_profile_schedule
_calibration_allows_followup = calibration_allows_followup
_calibration_pass_target_cap = calibration_pass_target_cap
_calibration_passes_for_cycle = calibration_passes_for_cycle
_calibration_targets_consumed = calibration_targets_consumed
_relevance_result_meaningfully_improved = relevance_result_meaningfully_improved
_remaining_daily_calibration_attempts = remaining_daily_calibration_attempts
_remaining_profile_rest_seconds = remaining_profile_rest_seconds
_profile_evaluation_policy = recovery_evaluation_policy


def main(argv: Sequence[str] | None = None) -> int:
    return _dispatch_command(
        argv,
        handlers=CommandHandlers(
            run=_run,
            evaluate=_evaluate,
            seed_baseline=_seed_baseline,
            discover_active=_discover_active,
            discover_public=_discover_public,
        ),
        request_stop=_request_orchestrator_stop,
    )


def _run(args) -> int:
    return run_command(
        args,
        RunCommandHooks(
            clear_stop=_STOP_EVENT.clear,
            state_store=StateStore,
            discover_profiles=lambda fail_fast: _discover_profiles(
                args,
                fail_fast=fail_fast,
            ),
            enabled_profiles=lambda: [
                profile
                for profile in _load_profiles(Path(args.profiles_json))
                if profile.enabled
            ],
            run_profile_cycle=lambda profile, store, policy, root_dir: (
                _run_profile_cycle(profile, args, store, policy, root_dir)
            ),
            stop_requested=_STOP_EVENT.is_set,
            monotonic=time.monotonic,
            sleep=time.sleep,
            log=lambda message: print(message, flush=True),
        ),
    )


_calibration_policy = calibration_policy_from_args
_profile_rest_seconds = profile_rest_seconds_from_args
_profile_schedule_policy = schedule_policy_from_args


def _discover_profiles(args, *, fail_fast: bool) -> None:
    if not args.discover_octo_profiles:
        return
    config = get_config()
    run_runtime_discovery(
        RuntimeDiscoveryRequest(
            enabled=args.discover_octo_profiles,
            profiles_path=Path(args.profiles_json),
            cli_token=args.octo_api_token,
            environment_token=os.environ.get("OCTO_API_TOKEN", ""),
            configured_token=config.facebook.octo_api_token,
            cli_search_tags=args.octo_search_tags,
            configured_search_tags=config.facebook.octo_search_tags,
            enable_new=args.enable_discovered,
            fail_fast=fail_fast,
        ),
        RuntimeDiscoveryHooks(
            merge_profiles=_merge_profile_catalog,
            log=lambda message: print(message, flush=True),
        ),
    )


def _merge_profile_catalog(
    path: Path,
    token: str,
    search_tags: str,
    enable_new: bool,
) -> int:
    return _merge_public_profiles(
        path,
        token=token,
        search_tags=search_tags,
        enable_new=enable_new,
    )


def _run_profile_cycle(
    profile: ProfileConfig,
    args,
    store: OrchestrationStateStore,
    policy: CalibrationPolicy,
    root_dir: Path,
) -> ProfileCycleSchedule:
    def execute_calibration(
        cycle_profile: Profile,
        collect_dir: Path,
        cycle_root: Path,
        decision: CalibrationDecision,
        target_offset: int,
        target_limit: int,
    ) -> dict[str, Any]:
        return _run_calibration(
            cycle_profile,
            args,
            collect_dir,
            cycle_root,
            decision=decision,
            target_offset=target_offset,
            target_limit_cap=target_limit,
        )

    return run_profile_cycle_command(
        ProfileCycleCommandRequest(
            profile=profile,
            state=store,
            policy=policy,
            schedule_policy=_profile_schedule_policy(args),
            root_dir=root_dir,
            collect_seconds=args.collect_minutes * 60,
            recovery_burst_cycles=args.recovery_burst_cycles,
            dry_run=args.dry_run,
        ),
        ProfileCycleCommandHooks(
            profile_lock=lambda cycle_root, profile_uuid: FileLock(
                profile_lock_path(cycle_root, profile_uuid)
            ),
            run_collection=lambda cycle_profile, collect_dir: _run_collection_pipeline(
                cycle_profile, args, collect_dir
            ),
            persist_profile_country=lambda profile_uuid, country: (
                _persist_profile_country(
                    Path(args.profiles_json),
                    profile_uuid,
                    country,
                )
            ),
            update_calibration_pools=_update_calibration_pools,
            count_calibration_targets=_count_calibration_targets,
            run_calibration=execute_calibration,
            stop_profile=lambda cycle_profile: _stop_octo_profile(
                cycle_profile,
                args,
            ),
            write_json=_write_json,
            stop_requested=_STOP_EVENT.is_set,
            now=lambda: datetime.now(UTC),
            log=lambda message: print(message, flush=True),
        ),
    )


def _run_collection_pipeline(
    profile: ProfileConfig,
    args,
    collect_dir: Path,
) -> CollectionPipelineState:
    return run_collection_command(
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
            run_command=lambda command, log_path, timeout: _run_command(
                command,
                log_path,
                timeout_seconds=timeout,
            ),
            collector_command=lambda cycle_profile, run_dir: _collector_command(
                cycle_profile,
                args,
                run_dir,
            ),
            classifier_command=lambda run_dir, stage, source, include_video: (
                _relevance_classifier_command(
                    run_dir,
                    stage=stage,
                    source=source,
                    include_video=include_video,
                )
            ),
            isolated_resolver_command=lambda cycle_profile, run_dir: (
                _isolated_landing_resolver_command(cycle_profile, args, run_dir)
            ),
            enricher_command=lambda cycle_profile, run_dir, source: (
                _relevant_enricher_command(
                    cycle_profile,
                    args,
                    run_dir,
                    source=source,
                )
            ),
            backend_import_command=_backend_import_command,
            stop_requested=_STOP_EVENT.is_set,
            relevance_enabled=lambda: _relevance_classification_enabled(args),
            artifact_exists=lambda path: path.exists(),
            audit_interest_safety=_interest_safe_collection_violations,
            write_json=_write_json,
            log=lambda message: print(message, flush=True),
        ),
    )


def _interest_safe_collection_violations(run_dir: Path) -> list[str]:
    summary = _load_json(run_dir / "summary.json", default={})
    ads = _load_json(run_dir / "ads.json", default=None)
    return interest_safety_violations(summary, ads)


def _collector_command(profile: ProfileConfig, args, run_dir: Path) -> list[str]:
    return build_collector_command(profile, args, run_dir, _octo_environment(args))


def _relevance_classifier_command(
    run_dir: Path,
    *,
    stage: str = "standard",
    source: Path | None = None,
    include_video: bool = False,
) -> list[str]:
    return build_relevance_classifier_command(
        run_dir,
        _python_environment(),
        stage=stage,
        source=source,
        include_video=include_video,
    )


def _relevant_enricher_command(
    profile: ProfileConfig,
    args,
    run_dir: Path,
    *,
    source: Path | None = None,
) -> list[str]:
    return build_relevant_enricher_command(
        profile,
        args,
        run_dir,
        _octo_environment(args),
        source=source,
    )


def _isolated_landing_resolver_command(
    profile: ProfileConfig,
    args,
    run_dir: Path,
) -> list[str]:
    return build_isolated_landing_resolver_command(
        profile,
        args,
        run_dir,
        _octo_environment(args),
    )


def _relevance_classification_enabled(args) -> bool:
    return relevance_classification_enabled(
        args.classify_relevance,
        get_config().facebook,
    )


def _backend_import_command(
    profile: ProfileConfig,
    ads_json_path: Path,
) -> list[str]:
    return build_backend_import_command(profile, ads_json_path, _python_environment())


def _python_environment() -> PythonProcessEnvironment:
    return python_process_environment(get_config().facebook)


def _octo_environment(args) -> OctoProcessEnvironment:
    return octo_process_environment(args, get_config().facebook)


def _calibrator_command(
    profile: ProfileConfig,
    args,
    run_dir: Path,
    ads_paths: list[Path],
    country: str | None,
    *,
    target_offset: int = 0,
    target_limit: int | None = None,
    min_successful_targets: int | None = None,
    max_reactions: int | None = None,
    max_follows: int | None = None,
    max_comments: int | None = None,
    min_interactions: int | None = None,
) -> list[str]:
    config = get_config()
    return build_calibration_command(
        profile,
        args,
        run_dir,
        ads_paths,
        country,
        CalibrationProcessEnvironment(
            executable=config.facebook.runner_python,
            octo_host=args.octo_host or config.facebook.octo_host,
            octo_port=args.octo_port or config.facebook.octo_port,
            octo_headless=_octo_headless(args),
        ),
        target_offset=target_offset,
        target_limit=target_limit,
        min_successful_targets=min_successful_targets,
        max_reactions=max_reactions,
        max_follows=max_follows,
        max_comments=max_comments,
        min_interactions=min_interactions,
    )


def _octo_headless(args) -> bool:
    return octo_headless(args.octo_headless, get_config().facebook)


def _calibration_plan(
    decision: CalibrationDecision,
    args,
    available_targets: int,
) -> CalibrationPlan:
    return plan_calibration_intensity(
        decision,
        CalibrationIntensityPolicy(
            standard_limit=args.calibration_limit,
            standard_goal=args.calibration_target_goal,
            recovery_limit=args.calibration_recovery_target_limit,
            recovery_goal=args.calibration_recovery_target_goal,
            low_relevance_goal=args.calibration_low_relevance_target_goal,
            funnel_enabled=args.calibration_offer_funnel,
            funnel_goal=args.calibration_funnel_target_goal,
            max_reactions=args.calibration_max_reactions,
            max_follows=args.calibration_max_follows,
            max_comments=args.calibration_max_comments,
            min_interactions=args.calibration_min_interactions,
            comment_every=args.calibration_comment_every,
        ),
        available_targets=available_targets,
    )


def _effective_calibration_target_goal(plan: CalibrationPlan) -> int:
    return effective_target_goal(plan)


def _run_calibration(
    profile: ProfileConfig,
    args,
    collect_dir: Path,
    root_dir: Path,
    *,
    decision: CalibrationDecision,
    target_offset: int = 0,
    target_limit_cap: int | None = None,
) -> dict[str, Any]:
    def calibrator_command(
        pass_profile: Profile,
        run_dir: Path,
        paths: list[Path],
        country: str | None,
        offset: int,
        plan: CalibrationPlan,
    ) -> list[str]:
        return _calibrator_command(
            pass_profile,
            args,
            run_dir,
            paths,
            country,
            target_offset=offset,
            target_limit=plan.target_limit,
            min_successful_targets=plan.target_goal,
            max_reactions=plan.max_reactions,
            max_follows=plan.max_follows,
            max_comments=plan.max_comments,
            min_interactions=plan.min_interactions,
        )

    return run_calibration_command(
        CalibrationPassRequest(
            profile=profile,
            collect_dir=collect_dir,
            root_dir=root_dir,
            decision=decision,
            default_elapsed_seconds=args.collect_minutes * 60,
            dry_run=args.dry_run,
            target_offset=target_offset,
            target_limit_cap=target_limit_cap,
        ),
        CalibrationCommandHooks(
            prepare_run_dir=_prepare_calibration_run_dir,
            target_sources=_calibration_ads_paths,
            count_targets=_count_calibration_targets,
            plan=lambda pass_decision, available: _calibration_plan(
                pass_decision,
                args,
                available,
            ),
            calibrator_command=calibrator_command,
            run_command=lambda command, log_path, timeout: _run_command(
                command,
                log_path,
                timeout_seconds=timeout,
            ),
            timeout_seconds=lambda target_limit: _calibration_timeout_seconds(
                args,
                target_limit=target_limit,
            ),
            load_json=lambda run_dir: _load_json(
                run_dir / "summary.json",
                default={},
            ),
            now=utc_now,
            log=lambda message: print(message, flush=True),
        ),
    )


def _prepare_calibration_run_dir(profile: ProfileConfig, root_dir: Path) -> Path:
    cycle_at = datetime.now(UTC).strftime("%Y%m%d_%H%M%S_%f")
    calibration_dir = (
        root_dir / "profiles" / profile.storage_name / f"calibration_{cycle_at}"
    )
    calibration_dir.mkdir(parents=True, exist_ok=True)
    return calibration_dir


def _run_command(
    command: list[str],
    log_path: Path,
    *,
    timeout_seconds: float | None = None,
    interrupt_grace_seconds: float = 30.0,
) -> int:
    return run_orchestrator_command(
        command,
        log_path,
        src_path=get_config().paths.src_path,
        registry=_PROCESS_REGISTRY,
        timeout_seconds=timeout_seconds,
        interrupt_grace_seconds=interrupt_grace_seconds,
    )


def _calibration_timeout_seconds(
    args,
    *,
    target_limit: int | None = None,
) -> float:
    return calibration_timeout_seconds(args, target_limit=target_limit)


def _request_orchestrator_stop(_signum, _frame) -> None:
    _STOP_EVENT.set()
    _PROCESS_REGISTRY.signal_all(signal.SIGINT)


def _evaluate(args) -> int:
    return run_evaluate_command(
        EvaluateCommandRequest(
            state_path=Path(args.state_json),
            run_dir=Path(args.run_dir),
            profile_uuid=args.profile_uuid,
            expected_country=args.expected_country or None,
            return_code=args.return_code,
            default_elapsed_seconds=args.default_elapsed_seconds,
            default_scrolls=args.default_scrolls,
            calibration_targets=args.calibration_targets,
        ),
        _maintenance_command_hooks(),
    )


def _seed_baseline(args) -> int:
    return run_seed_baseline_command(
        SeedBaselineCommandRequest(
            state_path=Path(args.state_json),
            run_dir=Path(args.run_dir),
            profile_uuid=args.profile_uuid,
            label=args.label,
            expected_country=args.expected_country or None,
            default_elapsed_seconds=args.default_elapsed_seconds,
            default_scrolls=args.default_scrolls,
        ),
        _maintenance_command_hooks(),
    )


def _maintenance_command_hooks() -> MaintenanceCommandHooks:
    return MaintenanceCommandHooks(
        state_store=StateStore,
        output=lambda message, flush: print(message, flush=flush),
    )


def _discover_active(args) -> int:
    profiles_path = Path(args.profiles_json)
    source = OctoActiveProfileSource(
        OctoProfileSessionManager(_local_octo_transport(args.octo_host, args.octo_port))
    )
    return run_active_discovery_command(
        enable_new=bool(args.enable_new),
        hooks=ActiveDiscoveryCommandHooks(
            discover=lambda enable_new: discover_catalog_profiles(
                profiles_path,
                source,
                enable_new=enable_new,
            ),
            log=print,
        ),
    )


def _discover_public(args) -> int:
    return run_public_discovery_command(
        PublicDiscoveryCommandRequest(
            profiles_path=Path(args.profiles_json),
            token=args.octo_api_token or os.environ.get("OCTO_API_TOKEN", ""),
            search_tags=args.octo_search_tags,
            enable_new=bool(args.enable_new),
        ),
        RuntimeDiscoveryHooks(
            merge_profiles=_merge_profile_catalog,
            log=print,
        ),
    )


def _merge_public_profiles(
    profiles_path: Path,
    *,
    token: str,
    search_tags: str = "",
    enable_new: bool = False,
) -> int:
    if not token:
        raise RuntimeError("Octo Public API token is required")
    source = OctoPayloadProfileSource(
        lambda tags: _octo_public_profiles(token, search_tags=tags)
    )
    result = discover_catalog_profiles(
        profiles_path,
        source,
        search_tags=search_tags,
        enable_new=enable_new,
    )
    return result.added


def _load_profiles(path: Path) -> list[ProfileConfig]:
    return list_catalog_profiles(path)


def _persist_profile_country(path: Path, profile_uuid: str, country: str) -> None:
    adopt_catalog_country(path, profile_uuid, country)


def _count_calibration_targets(
    profile: ProfileConfig,
    collect_dir: Path,
    root_dir: Path | None = None,
) -> int:
    return persistent_target_pool().count(profile, collect_dir, root_dir)


def _calibration_ads_paths(
    profile: ProfileConfig,
    collect_dir: Path,
    root_dir: Path | None = None,
) -> list[Path]:
    return persistent_target_pool().source_paths(profile, collect_dir, root_dir)


def _update_calibration_pools(
    profile: ProfileConfig,
    collect_dir: Path,
    root_dir: Path,
) -> None:
    persistent_target_pool().update(profile, collect_dir, root_dir)


def _octo_local_get(host: str, port: int, path: str) -> dict | list:
    return OctoHttpClient(f"http://{host}:{port}").request("GET", path)


def _octo_local_post(
    host: str,
    port: int,
    path: str,
    body: dict[str, Any],
) -> dict | list:
    return OctoHttpClient(f"http://{host}:{port}").request("POST", path, body)


def _local_octo_transport(host: str, port: int) -> CallbackOctoTransport:
    return CallbackOctoTransport(
        get=lambda path: _octo_local_get(host, port, path),
        post=lambda path, body: _octo_local_post(host, port, path, body),
    )


def _stop_octo_profile(profile: ProfileConfig, args) -> None:
    config = get_config()
    host = args.octo_host or config.facebook.octo_host
    port = args.octo_port or config.facebook.octo_port
    try:
        sessions = OctoProfileSessionManager(_local_octo_transport(host, port))
        if not any(
            active.octo_profile_uuid == profile.octo_profile_uuid
            for active in sessions.active()
        ):
            return
        sessions.stop(profile.octo_profile_uuid)
        print(f"[{profile.display_name}] Octo profile stopped", flush=True)
    except Exception as exc:
        print(
            f"[{profile.display_name}] Octo profile stop failed: {exc!r}",
            flush=True,
        )


def _octo_public_profiles(token: str, *, search_tags: str = "") -> list[dict[str, Any]]:
    source = OctoPublicProfileSource(
        OctoHttpClient(
            "https://app.octobrowser.net",
            token=token,
        )
    )
    return [
        {"uuid": profile.octo_profile_uuid, "title": profile.label}
        for profile in source.discover(search_tags=search_tags)
    ]


def _load_json(path: Path, *, default: Any) -> Any:
    if not path.exists():
        return default
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return default


def _write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(path)


def utc_now() -> str:
    return datetime.now(UTC).isoformat()


if __name__ == "__main__":
    raise SystemExit(main())

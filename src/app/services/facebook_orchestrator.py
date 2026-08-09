"""Profile-level Facebook collector orchestrator.

This is intentionally a thin CLI layer over the existing runner and calibrator.
It keeps state in JSON files, runs one job per Octo profile at a time, and does
not require backend or frontend changes.
"""

from __future__ import annotations

import json
import os
import signal
import subprocess
import threading
import time
from collections.abc import Sequence
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from app.facebook.adapters.octo import (
    OctoActiveProfileSource,
    OctoHttpClient,
    OctoProfileSessionManager,
    OctoPublicProfileSource,
)
from app.facebook.calibration import (
    CalibrationIntensityPolicy,
    CalibrationPassHooks,
    CalibrationPassRequest,
    CalibrationPassService,
    CalibrationPlan,
    CalibrationProcessEnvironment,
    JsonCalibrationTargetPool,
    build_calibration_command,
    calibration_pool_name,
    calibration_timeout_seconds,
    effective_target_goal,
    is_direct_calibration_target,
    is_relevant_ad,
    load_saved_facebook_targets_from_ads_json,
    plan_calibration_intensity,
    quarantined_facebook_post_urls,
)
from app.facebook.collection import interest_safety_violations
from app.facebook.orchestration import (
    CollectionPipelineState,
    OrchestrationStateStore,
    ProfileCycleSchedule,
    ProfileEvaluationService,
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
    SubprocessCommandRunner,
    build_backend_import_command,
    build_collector_command,
    build_isolated_landing_resolver_command,
    build_relevance_classifier_command,
    build_relevant_enricher_command,
    profile_lock_path,
    signal_process_group,
    write_log_line,
)
from app.facebook.orchestration.commands import (
    CollectionCommandHooks,
    CollectionCommandRequest,
    CommandHandlers,
    ProfileCycleCommandHooks,
    ProfileCycleCommandRequest,
    RunCommandHooks,
    build_parser,
    calibration_policy_from_args,
    log_profile_schedule,
    profile_rest_seconds_from_args,
    run_collection_command,
    run_command,
    run_profile_cycle_command,
    schedule_policy_from_args,
)
from app.facebook.orchestration.commands import dispatch as _dispatch_command
from app.facebook.orchestration.lifecycle import (
    baseline_from_run_records,
    calibration_was_effective,
    is_healthy_relevance_result,
)
from app.facebook.profiles import (
    DiscoveredProfile,
    Profile,
    ProfileDiscoveryService,
    ProfileService,
)
from app.facebook.profiles.adapters import JsonProfileCatalog
from app.services.facebook.health import (
    CalibrationDecision,
    CalibrationPolicy,
    collect_run_metrics,
    is_good_baseline_candidate,
)
from app.settings import get_config

_POOL_FILE_LOCK = threading.Lock()
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


def _log_profile_schedule(
    profile: ProfileConfig,
    schedule: ProfileCycleSchedule,
    *,
    burst_limit: int,
) -> None:
    log_profile_schedule(
        profile,
        schedule,
        burst_limit=burst_limit,
        log=lambda message: print(message, flush=True),
    )


def _discover_profiles(args, *, fail_fast: bool) -> None:
    if not args.discover_octo_profiles:
        return
    config = get_config()
    token = (
        args.octo_api_token
        or os.environ.get("OCTO_API_TOKEN", "")
        or config.facebook.octo_api_token
    )
    search_tags = args.octo_search_tags or config.facebook.octo_search_tags
    if not token:
        print(
            "[orchestrator] Octo Public API discovery skipped: token is not "
            "configured; using profiles.json",
            flush=True,
        )
        return
    try:
        added = _merge_public_profiles(
            Path(args.profiles_json),
            token=token,
            search_tags=search_tags,
            enable_new=args.enable_discovered,
        )
        if added:
            print(f"[orchestrator] discovered {added} new Octo profile(s)", flush=True)
    except Exception as exc:
        if fail_fast:
            raise
        print(f"[orchestrator] Octo discovery failed: {exc!r}", flush=True)


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
    if args.classify_relevance is not None:
        return bool(args.classify_relevance)
    return bool(get_config().facebook.relevance_filter_enabled)


def _backend_import_command(
    profile: ProfileConfig,
    ads_json_path: Path,
) -> list[str]:
    return build_backend_import_command(profile, ads_json_path, _python_environment())


def _python_environment() -> PythonProcessEnvironment:
    return PythonProcessEnvironment(executable=get_config().facebook.runner_python)


def _octo_environment(args) -> OctoProcessEnvironment:
    config = get_config()
    return OctoProcessEnvironment(
        executable=config.facebook.runner_python,
        collector_module=config.facebook.runner_module,
        host=args.octo_host or config.facebook.octo_host,
        port=args.octo_port or config.facebook.octo_port,
        headless=_octo_headless(args),
    )


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
    if args.octo_headless is not None:
        return bool(args.octo_headless)
    return bool(get_config().facebook.octo_headless)


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
    hooks = CalibrationPassHooks(
        prepare_run_dir=_prepare_calibration_run_dir,
        target_sources=_calibration_ads_paths,
        count_targets=_count_calibration_targets,
        plan=lambda pass_decision, available: _calibration_plan(
            pass_decision,
            args,
            available,
        ),
        observe_country=lambda pass_profile, run_dir, elapsed: (
            collect_run_metrics(
                run_dir,
                expected_country=pass_profile.expected_country,
                default_elapsed_seconds=elapsed,
            ).profile_country
            or pass_profile.expected_country
        ),
        execute=lambda pass_profile, run_dir, paths, country, offset, plan: (
            _run_command(
                _calibrator_command(
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
                ),
                run_dir / "calibrator.log",
                timeout_seconds=_calibration_timeout_seconds(
                    args,
                    target_limit=plan.target_limit,
                ),
            )
        ),
        load_summary=lambda run_dir: _load_json(
            run_dir / "summary.json",
            default={},
        ),
        now=utc_now,
        log=lambda message: print(message, flush=True),
    )
    return CalibrationPassService(hooks).run(
        CalibrationPassRequest(
            profile=profile,
            collect_dir=collect_dir,
            root_dir=root_dir,
            decision=decision,
            default_elapsed_seconds=args.collect_minutes * 60,
            dry_run=args.dry_run,
            target_offset=target_offset,
            target_limit_cap=target_limit_cap,
        )
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
    env = os.environ.copy()
    env.setdefault("PYTHONPATH", str(get_config().paths.src_path))
    env["PW_TEST_SCREENSHOT_NO_FONTS_READY"] = "1"
    return SubprocessCommandRunner(
        cwd=get_config().paths.src_path.parent,
        env=env,
        registry=_PROCESS_REGISTRY,
    ).run(
        command,
        log_path,
        timeout_seconds=timeout_seconds,
        interrupt_grace_seconds=interrupt_grace_seconds,
    )


def _calibration_timeout_seconds(
    args,
    *,
    target_limit: int | None = None,
) -> float:
    return calibration_timeout_seconds(args, target_limit=target_limit)


def _write_log_line(log_file, message: str) -> None:
    write_log_line(log_file, message)


def _signal_process_group(process: subprocess.Popen, sig: signal.Signals) -> None:
    signal_process_group(process, sig)


def _request_orchestrator_stop(_signum, _frame) -> None:
    _STOP_EVENT.set()
    _PROCESS_REGISTRY.signal_all(signal.SIGINT)


def _evaluate(args) -> int:
    policy = CalibrationPolicy()
    store = StateStore(Path(args.state_json))
    metrics = collect_run_metrics(
        args.run_dir,
        expected_country=args.expected_country or None,
        return_code=args.return_code,
        default_elapsed_seconds=args.default_elapsed_seconds,
        default_scrolls=args.default_scrolls,
        calibration_targets_available=args.calibration_targets,
    )
    decision = (
        ProfileEvaluationService(store)
        .evaluate(
            args.profile_uuid,
            metrics,
            policy,
            load_recovery_context=False,
            exclude_run_dir=metrics.run_dir,
        )
        .decision
    )
    print(json.dumps(decision.to_dict(), ensure_ascii=False, indent=2))
    return 0 if not decision.should_calibrate else 10


def _seed_baseline(args) -> int:
    policy = CalibrationPolicy()
    metrics = collect_run_metrics(
        args.run_dir,
        expected_country=args.expected_country or None,
        default_elapsed_seconds=args.default_elapsed_seconds,
        default_scrolls=args.default_scrolls,
    )
    if not is_good_baseline_candidate(metrics, policy):
        print(
            "Run is not a good baseline candidate. "
            "Use a complete, geo-matched run with enough ads and targets.",
            flush=True,
        )
        print(json.dumps(metrics.to_dict(), ensure_ascii=False, indent=2))
        return 1
    baseline = StateStore(Path(args.state_json)).seed_baseline(
        args.profile_uuid,
        metrics,
        label=args.label,
        expected_country=args.expected_country or None,
        policy=policy,
    )
    print(json.dumps(baseline.to_dict(), ensure_ascii=False, indent=2))
    return 0


class _PublicProfilesCompatibilitySource:
    def __init__(self, token: str) -> None:
        self._token = token

    def discover(self, *, search_tags: str = "") -> list[DiscoveredProfile]:
        return [
            DiscoveredProfile(
                octo_profile_uuid=str(raw.get("uuid") or ""),
                label=str(raw.get("title") or str(raw.get("uuid") or "")[:8]),
            )
            for raw in _octo_public_profiles(self._token, search_tags=search_tags)
            if raw.get("uuid")
        ]


class _LocalOctoCompatibilityTransport:
    def __init__(self, host: str, port: int) -> None:
        self._host = host
        self._port = port

    def request(
        self,
        method: str,
        path: str,
        body: dict[str, Any] | None = None,
        *,
        timeout_seconds: float | None = None,
    ) -> dict[str, Any] | list[Any]:
        del timeout_seconds
        if method == "GET":
            return _octo_local_get(self._host, self._port, path)
        return _octo_local_post(self._host, self._port, path, body or {})


def _discover_active(args) -> int:
    profiles_path = Path(args.profiles_json)
    sessions = OctoProfileSessionManager(
        _LocalOctoCompatibilityTransport(args.octo_host, args.octo_port)
    )
    result = ProfileDiscoveryService(
        JsonProfileCatalog(profiles_path),
        OctoActiveProfileSource(sessions),
    ).discover(enable_new=bool(args.enable_new))
    print(f"active={result.discovered} added={result.added}")
    return 0


def _discover_public(args) -> int:
    added = _merge_public_profiles(
        Path(args.profiles_json),
        token=args.octo_api_token or os.environ.get("OCTO_API_TOKEN", ""),
        search_tags=args.octo_search_tags,
        enable_new=bool(args.enable_new),
    )
    print(f"added={added}")
    return 0


def _merge_public_profiles(
    profiles_path: Path,
    *,
    token: str,
    search_tags: str = "",
    enable_new: bool = False,
) -> int:
    if not token:
        raise RuntimeError("Octo Public API token is required")
    result = ProfileDiscoveryService(
        JsonProfileCatalog(profiles_path),
        _PublicProfilesCompatibilitySource(token),
    ).discover(search_tags=search_tags, enable_new=enable_new)
    return result.added


def _load_profiles(path: Path) -> list[ProfileConfig]:
    return ProfileService(JsonProfileCatalog(path)).list_profiles()


def _persist_profile_country(path: Path, profile_uuid: str, country: str) -> None:
    ProfileService(JsonProfileCatalog(path)).adopt_country(profile_uuid, country)


def _count_calibration_targets(
    profile: ProfileConfig,
    collect_dir: Path,
    root_dir: Path | None = None,
) -> int:
    return _calibration_target_pool().count(profile, collect_dir, root_dir)


def _calibration_ads_paths(
    profile: ProfileConfig,
    collect_dir: Path,
    root_dir: Path | None = None,
) -> list[Path]:
    return _calibration_target_pool().source_paths(profile, collect_dir, root_dir)


def _update_calibration_pools(
    profile: ProfileConfig,
    collect_dir: Path,
    root_dir: Path,
) -> None:
    _calibration_target_pool().update(profile, collect_dir, root_dir)


def _has_relevant_ads(path: Path) -> bool:
    return _calibration_target_pool().has_relevant_ads(path)


def _has_direct_relevant_ads(path: Path) -> bool:
    return _calibration_target_pool().has_direct_relevant_ads(path)


_ad_is_direct_calibration_target = is_direct_calibration_target
_ad_is_relevant = is_relevant_ad
_safe_name = calibration_pool_name


def _calibration_target_pool() -> JsonCalibrationTargetPool:
    return JsonCalibrationTargetPool(
        load_saved_facebook_targets_from_ads_json,
        quarantined_facebook_post_urls,
        lock=_POOL_FILE_LOCK,
    )


def _octo_local_get(host: str, port: int, path: str) -> dict | list:
    return OctoHttpClient(f"http://{host}:{port}").request("GET", path)


def _octo_local_post(
    host: str,
    port: int,
    path: str,
    body: dict[str, Any],
) -> dict | list:
    return OctoHttpClient(f"http://{host}:{port}").request("POST", path, body)


def _stop_octo_profile(profile: ProfileConfig, args) -> None:
    config = get_config()
    host = args.octo_host or config.facebook.octo_host
    port = args.octo_port or config.facebook.octo_port
    try:
        sessions = OctoProfileSessionManager(
            _LocalOctoCompatibilityTransport(host, port)
        )
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

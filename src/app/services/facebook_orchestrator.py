"""Profile-level Facebook collector orchestrator.

This is intentionally a thin CLI layer over the existing runner and calibrator.
It keeps state in JSON files, runs one job per Octo profile at a time, and does
not require backend or frontend changes.
"""

from __future__ import annotations

import argparse
import json
import os
import signal
import subprocess
import threading
import time
from collections.abc import Sequence
from contextlib import contextmanager
from dataclasses import replace
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
    plan_calibration_intensity,
)
from app.facebook.collection import interest_safety_violations
from app.facebook.orchestration import (
    CollectionPipelineHooks,
    CollectionPipelineRequest,
    CollectionPipelineService,
    CollectionPipelineState,
    OrchestrationRunHooks,
    OrchestrationRunRequest,
    OrchestrationService,
    OrchestrationStateStore,
    ProfileCycleHooks,
    ProfileCycleRequest,
    ProfileCycleSchedule,
    ProfileCycleService,
    ProfileEvaluationService,
    ProfileScheduler,
    RecoverySchedulePolicy,
    SchedulerConfig,
    SchedulerHooks,
    calibration_allows_followup,
    calibration_pass_target_cap,
    calibration_passes_for_cycle,
    calibration_targets_consumed,
    next_profile_schedule,
    profile_rest_seconds,
    recovery_evaluation_policy,
    recovery_schedule_policy,
    relevance_result_meaningfully_improved,
    remaining_daily_calibration_attempts,
    validate_orchestration_run_options,
)
from app.facebook.orchestration import (
    remaining_profile_rest_seconds as _remaining_profile_rest_seconds,
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
from app.services.facebook.calibration import (
    load_saved_facebook_targets_from_ads_json,
    quarantined_facebook_post_urls,
)
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
_profile_evaluation_policy = recovery_evaluation_policy


def main(argv: Sequence[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)
    if args.command == "run":
        signal.signal(signal.SIGINT, _request_orchestrator_stop)
        signal.signal(signal.SIGTERM, _request_orchestrator_stop)
        return _run(args)
    if args.command == "evaluate":
        return _evaluate(args)
    if args.command == "seed-baseline":
        return _seed_baseline(args)
    if args.command == "discover-active":
        return _discover_active(args)
    if args.command == "discover-octo":
        return _discover_public(args)
    parser.print_help()
    return 2


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command")

    run = sub.add_parser("run", help="Run profile collect/evaluate/calibrate cycles.")
    _add_common_paths(run)
    run.add_argument(
        "--profiles-json", default="storage/facebook/orchestrator/profiles.json"
    )
    run.add_argument("--max-parallel", type=int, default=2)
    run.add_argument("--loop", action="store_true")
    run.add_argument("--cycle-sleep", type=float, default=60.0)
    run.add_argument(
        "--profile-rest-minutes",
        type=float,
        default=0.0,
        help=(
            "Minimum rest after a profile finishes collection and optional "
            "calibration. The larger of this value and --cycle-sleep is used."
        ),
    )
    run.add_argument(
        "--recovery-burst-cycles",
        type=int,
        default=3,
        help=(
            "Number of collect/calibrate recovery cycles run without the normal "
            "profile rest before applying backoff."
        ),
    )
    run.add_argument(
        "--recovery-burst-rest-minutes",
        type=float,
        default=0.0,
        help="Delay before the next validation collection inside a recovery burst.",
    )
    run.add_argument(
        "--infrastructure-retry-minutes",
        type=float,
        default=5.0,
        help="Retry delay after Octo, proxy, or calibration infrastructure errors.",
    )
    run.add_argument("--discovery-interval", type=float, default=300.0)
    run.add_argument("--max-cycles", type=int, default=0, help=argparse.SUPPRESS)
    run.add_argument("--collect-minutes", type=float, default=15.0)
    run.add_argument("--collect-timeout-grace", type=float, default=180.0)
    run.add_argument("--collect-scrolls", type=int, default=10000)
    run.add_argument("--resolve-max", type=int, default=200)
    run.add_argument("--scroll-px", type=int, default=520)
    run.add_argument("--max-ads-per-view", type=int, default=1)
    run.add_argument("--landing-archive-timeout", type=float, default=12.0)
    run.add_argument("--landing-archive-max-resources", type=int, default=80)
    run.add_argument("--video-max-seconds", type=float, default=10.0)
    run.add_argument("--no-video-recording", action="store_true")
    run.add_argument("--no-landing-archives", action="store_true")
    run.add_argument(
        "--interest-safe-collection",
        action=argparse.BooleanOptionalAction,
        default=True,
        help=(
            "Passively scan the feed, classify cards first, and allow active "
            "browser actions only for relevance-gated ads."
        ),
    )
    run.add_argument(
        "--relevant-enrichment",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="Capture video and landing artifacts only for prefiltered ads.",
    )
    run.add_argument(
        "--isolated-hold-resolution",
        action=argparse.BooleanOptionalAction,
        default=True,
        help=(
            "Resolve uncertain passive CTA URLs in a cookie-free context before "
            "allowing any authenticated profile action."
        ),
    )
    run.add_argument("--isolated-resolution-timeout", type=float, default=900.0)
    run.add_argument("--enrichment-timeout", type=float, default=1200.0)
    run.add_argument("--octo-host", default="")
    run.add_argument("--octo-port", type=int, default=0)
    run.add_argument(
        "--octo-headless",
        action=argparse.BooleanOptionalAction,
        default=None,
    )
    run.add_argument("--debug", action="store_true")
    run.add_argument("--dry-run", action="store_true")
    run.add_argument("--calibration-limit", type=int, default=20)
    run.add_argument("--calibration-target-goal", type=int, default=10)
    run.add_argument(
        "--calibration-low-relevance-target-goal",
        type=int,
        default=30,
    )
    run.add_argument(
        "--calibration-recovery-target-goal",
        type=int,
        default=40,
    )
    run.add_argument(
        "--calibration-recovery-target-limit",
        type=int,
        default=50,
    )
    run.add_argument("--calibration-timeout-grace", type=float, default=180.0)
    run.add_argument("--calibration-view-seconds", type=float, default=45.0)
    run.add_argument("--calibration-pause", type=float, default=2.0)
    run.add_argument("--calibration-locate-timeout", type=float, default=12.0)
    run.add_argument("--calibration-page-timeout", type=float, default=45.0)
    run.add_argument(
        "--calibration-visit-landing",
        action=argparse.BooleanOptionalAction,
        default=True,
    )
    run.add_argument("--calibration-landing-view-seconds", type=float, default=45.0)
    run.add_argument("--calibration-landing-timeout", type=float, default=20.0)
    run.add_argument(
        "--calibration-offer-funnel",
        action=argparse.BooleanOptionalAction,
        default=True,
    )
    run.add_argument(
        "--calibration-direct-offer-fallback",
        action=argparse.BooleanOptionalAction,
        default=True,
    )
    run.add_argument("--calibration-session-minutes", type=float, default=15.0)
    run.add_argument(
        "--calibration-repeat-targets-until-deadline",
        action=argparse.BooleanOptionalAction,
        default=True,
    )
    run.add_argument("--calibration-funnel-target-goal", type=int, default=3)
    run.add_argument("--calibration-prelander-max-scrolls", type=int, default=12)
    run.add_argument("--calibration-quiz-max-questions", type=int, default=10)
    run.add_argument(
        "--calibration-offer-submit-mode",
        choices=("disabled", "fill_only", "allowlisted"),
        default="disabled",
    )
    run.add_argument(
        "--calibration-offer-submit-allow-domain",
        action="append",
        default=[
            value.strip()
            for value in os.getenv(
                "FACEBOOK_CALIBRATION_OFFER_SUBMIT_ALLOW_DOMAINS",
                "",
            ).split(",")
            if value.strip()
        ],
    )
    run.add_argument(
        "--calibration-offer-identity-json",
        default=os.getenv("FACEBOOK_CALIBRATION_OFFER_IDENTITY_JSON", ""),
    )
    run.add_argument(
        "--calibration-offer-success-wait-seconds", type=float, default=20.0
    )
    run.add_argument("--calibration-max-retained-offer-tabs", type=int, default=6)
    run.add_argument("--min-calibration-targets", type=int, default=2)
    run.add_argument("--calibration-cooldown-hours", type=float, default=1.0)
    run.add_argument(
        "--soft-drop-calibration-windows",
        type=int,
        default=3,
    )
    run.add_argument("--watch-drop-ratio", type=float, default=0.70)
    run.add_argument("--immediate-drop-ratio", type=float, default=0.70)
    run.add_argument(
        "--minimum-healthy-relevant-rate",
        type=float,
        default=0.75,
    )
    run.add_argument(
        "--minimum-healthy-relevant-ads",
        type=int,
        default=15,
    )
    run.add_argument("--zero-ads-windows", type=int, default=2)
    run.add_argument("--absolute-low-ads-windows", type=int, default=2)
    run.add_argument("--absolute-low-ads-per-hour", type=float, default=12.0)
    run.add_argument(
        "--zero-ads-calibration-cooldown-minutes",
        type=float,
        default=30.0,
    )
    run.add_argument("--zero-ads-calibration-burst-limit", type=int, default=8)
    run.add_argument(
        "--zero-ads-calibration-backoff-hours",
        type=float,
        default=2.0,
    )
    run.add_argument("--calibration-retry-cooldown-hours", type=float, default=0.5)
    run.add_argument(
        "--maintenance-calibration-hours",
        type=float,
        default=6.0,
    )
    run.add_argument(
        "--maintenance-min-valid-windows",
        type=int,
        default=3,
    )
    run.add_argument("--max-calibrations-per-24h", type=int, default=24)
    run.add_argument("--calibration-reaction-rate", type=float, default=0.65)
    run.add_argument("--calibration-follow-rate", type=float, default=0.20)
    run.add_argument("--calibration-comment-every", type=int, default=0)
    run.add_argument("--calibration-max-reactions", type=int, default=6)
    run.add_argument("--calibration-max-follows", type=int, default=2)
    run.add_argument("--calibration-max-comments", type=int, default=0)
    run.add_argument("--calibration-min-interactions", type=int, default=1)
    run.add_argument("--calibration-comment-template", action="append", default=[])
    run.add_argument(
        "--classify-relevance",
        action=argparse.BooleanOptionalAction,
        default=None,
    )
    run.add_argument("--relevance-timeout", type=float, default=900.0)
    run.add_argument(
        "--import-backend",
        action=argparse.BooleanOptionalAction,
        default=False,
        help="Import each completed classified run into the application database.",
    )
    run.add_argument("--backend-import-timeout", type=float, default=300.0)
    run.add_argument("--discover-octo-profiles", action="store_true")
    run.add_argument("--octo-api-token", default="")
    run.add_argument("--octo-search-tags", default="")
    run.add_argument("--enable-discovered", action="store_true")

    evaluate = sub.add_parser("evaluate", help="Evaluate one existing collect run.")
    _add_common_paths(evaluate)
    evaluate.add_argument("--run-dir", required=True)
    evaluate.add_argument("--profile-uuid", default="")
    evaluate.add_argument("--expected-country", default="")
    evaluate.add_argument("--return-code", type=int)
    evaluate.add_argument("--default-elapsed-seconds", type=float)
    evaluate.add_argument("--default-scrolls", type=int)
    evaluate.add_argument("--calibration-targets", type=int)

    seed = sub.add_parser(
        "seed-baseline", help="Record an existing good run as baseline."
    )
    _add_common_paths(seed)
    seed.add_argument("--run-dir", required=True)
    seed.add_argument("--profile-uuid", required=True)
    seed.add_argument("--label", default="")
    seed.add_argument("--expected-country", default="")
    seed.add_argument("--default-elapsed-seconds", type=float)
    seed.add_argument("--default-scrolls", type=int)

    discover = sub.add_parser(
        "discover-active", help="Merge active Octo profiles into profiles JSON."
    )
    discover.add_argument(
        "--profiles-json", default="storage/facebook/orchestrator/profiles.json"
    )
    discover.add_argument("--octo-host", default="127.0.0.1")
    discover.add_argument("--octo-port", type=int, default=58888)
    discover.add_argument("--enable-new", action="store_true")

    discover_public = sub.add_parser(
        "discover-octo", help="Merge Octo Public API profiles into profiles JSON."
    )
    discover_public.add_argument(
        "--profiles-json", default="storage/facebook/orchestrator/profiles.json"
    )
    discover_public.add_argument("--octo-api-token", default="")
    discover_public.add_argument("--octo-search-tags", default="")
    discover_public.add_argument("--enable-new", action="store_true")
    return parser


def _add_common_paths(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--root-dir", default="storage/facebook/orchestrator")
    parser.add_argument(
        "--state-json", default="storage/facebook/orchestrator/state.json"
    )


def _run(args) -> int:
    _STOP_EVENT.clear()
    store = StateStore(Path(args.state_json))
    root_dir = Path(args.root_dir)
    policy = _calibration_policy(args)
    validate_orchestration_run_options(args)
    return OrchestrationService(
        OrchestrationRunHooks(
            discover_profiles=lambda: _discover_profiles(args, fail_fast=True),
            run_once=lambda: _run_once(args, store, policy, root_dir),
            run_continuously=lambda: _run_continuously(
                args,
                store,
                policy,
                root_dir,
            ),
        )
    ).run(OrchestrationRunRequest(continuous=args.loop))


def _calibration_policy(args) -> CalibrationPolicy:
    if args.calibration_cooldown_hours < 0:
        raise ValueError("--calibration-cooldown-hours cannot be negative")
    if args.soft_drop_calibration_windows < 2:
        raise ValueError("--soft-drop-calibration-windows must be at least 2")
    if not 0 < args.watch_drop_ratio <= 1:
        raise ValueError("--watch-drop-ratio must be greater than 0 and at most 1")
    if not 0 < args.immediate_drop_ratio <= 1:
        raise ValueError("--immediate-drop-ratio must be greater than 0 and at most 1")
    if not 0 < args.minimum_healthy_relevant_rate <= 1:
        raise ValueError(
            "--minimum-healthy-relevant-rate must be greater than 0 and at most 1"
        )
    if args.minimum_healthy_relevant_ads < 1:
        raise ValueError("--minimum-healthy-relevant-ads must be at least 1")
    if args.zero_ads_windows < 1:
        raise ValueError("--zero-ads-windows must be at least 1")
    if args.absolute_low_ads_windows < 1:
        raise ValueError("--absolute-low-ads-windows must be at least 1")
    if args.absolute_low_ads_per_hour < 0:
        raise ValueError("--absolute-low-ads-per-hour cannot be negative")
    if args.zero_ads_calibration_cooldown_minutes < 0:
        raise ValueError("--zero-ads-calibration-cooldown-minutes cannot be negative")
    if args.zero_ads_calibration_burst_limit < 1:
        raise ValueError("--zero-ads-calibration-burst-limit must be at least 1")
    if args.zero_ads_calibration_backoff_hours < 0:
        raise ValueError("--zero-ads-calibration-backoff-hours cannot be negative")
    if args.calibration_retry_cooldown_hours < 0:
        raise ValueError("--calibration-retry-cooldown-hours cannot be negative")
    if args.maintenance_calibration_hours < 0:
        raise ValueError("--maintenance-calibration-hours cannot be negative")
    if args.maintenance_min_valid_windows < 1:
        raise ValueError("--maintenance-min-valid-windows must be at least 1")
    if args.max_calibrations_per_24h < 1:
        raise ValueError("--max-calibrations-per-24h must be at least 1")
    return replace(
        CalibrationPolicy(),
        zero_ads_windows=args.zero_ads_windows,
        absolute_low_ads_windows=args.absolute_low_ads_windows,
        absolute_low_ads_per_hour=args.absolute_low_ads_per_hour,
        soft_drop_calibration_windows=args.soft_drop_calibration_windows,
        watch_drop_ratio=args.watch_drop_ratio,
        immediate_drop_ratio=args.immediate_drop_ratio,
        minimum_healthy_relevant_rate=args.minimum_healthy_relevant_rate,
        minimum_healthy_relevant_ads=args.minimum_healthy_relevant_ads,
        calibration_cooldown_seconds=args.calibration_cooldown_hours * 60 * 60,
        zero_ads_calibration_cooldown_seconds=(
            args.zero_ads_calibration_cooldown_minutes * 60
        ),
        zero_ads_calibration_burst_limit=args.zero_ads_calibration_burst_limit,
        zero_ads_calibration_backoff_seconds=(
            args.zero_ads_calibration_backoff_hours * 60 * 60
        ),
        calibration_retry_cooldown_seconds=(
            args.calibration_retry_cooldown_hours * 60 * 60
        ),
        maintenance_calibration_interval_seconds=(
            args.maintenance_calibration_hours * 60 * 60
        ),
        maintenance_min_valid_windows=args.maintenance_min_valid_windows,
        max_calibrations_per_24h=args.max_calibrations_per_24h,
        min_calibration_targets=args.min_calibration_targets,
        min_successful_calibration_targets=args.min_calibration_targets,
    )


def _run_once(
    args,
    store: OrchestrationStateStore,
    policy: CalibrationPolicy,
    root_dir: Path,
) -> int:
    return _profile_scheduler(args, store, policy, root_dir).run_once()


def _run_continuously(
    args,
    store: OrchestrationStateStore,
    policy: CalibrationPolicy,
    root_dir: Path,
) -> int:
    """Schedule each profile independently without a global cycle barrier."""
    return _profile_scheduler(args, store, policy, root_dir).run_continuously()


def _profile_scheduler(
    args,
    store: OrchestrationStateStore,
    policy: CalibrationPolicy,
    root_dir: Path,
) -> ProfileScheduler:
    schedule_policy = _profile_schedule_policy(args)
    return ProfileScheduler(
        SchedulerConfig(
            max_parallel=args.max_parallel,
            default_rest_seconds=schedule_policy.normal_rest_seconds,
            infrastructure_retry_seconds=(schedule_policy.infrastructure_retry_seconds),
            discovery_interval_seconds=args.discovery_interval,
            max_cycles=args.max_cycles,
        ),
        store,
        SchedulerHooks(
            discover_profiles=lambda: _discover_profiles(args, fail_fast=False),
            enabled_profiles=lambda: _enabled_profiles(args),
            run_profile_cycle=lambda profile: _run_profile_cycle(
                profile,
                args,
                store,
                policy,
                root_dir,
            ),
            remaining_profile_rest_seconds=lambda profile_uuid, rest_seconds: (
                _remaining_profile_rest_seconds(
                    store.profile_last_run_at(profile_uuid),
                    rest_seconds,
                )
            ),
            log=lambda message: print(message, flush=True),
            log_schedule=lambda profile, schedule: _log_profile_schedule(
                profile,
                schedule,
                burst_limit=args.recovery_burst_cycles,
            ),
        ),
        stop_requested=_STOP_EVENT.is_set,
        monotonic=time.monotonic,
        sleep=time.sleep,
    )


def _enabled_profiles(args) -> list[ProfileConfig]:
    return [
        profile
        for profile in _load_profiles(Path(args.profiles_json))
        if profile.enabled
    ]


def _profile_rest_seconds(args) -> float:
    return profile_rest_seconds(
        cycle_sleep_seconds=args.cycle_sleep,
        profile_rest_minutes=args.profile_rest_minutes,
    )


def _profile_schedule_policy(args) -> RecoverySchedulePolicy:
    return recovery_schedule_policy(
        cycle_sleep_seconds=args.cycle_sleep,
        profile_rest_minutes=args.profile_rest_minutes,
        recovery_burst_cycles=args.recovery_burst_cycles,
        recovery_burst_rest_minutes=args.recovery_burst_rest_minutes,
        infrastructure_retry_minutes=args.infrastructure_retry_minutes,
    )


def _log_profile_schedule(
    profile: ProfileConfig,
    schedule: ProfileCycleSchedule,
    *,
    burst_limit: int,
) -> None:
    if schedule.kind == "recovery_burst":
        delay = (
            "immediately"
            if schedule.rest_seconds <= 0
            else f"in {schedule.rest_seconds / 60:.1f}m"
        )
        print(
            f"[{profile.display_name}] recovery="
            f"{schedule.recovery_attempt}/{burst_limit}; "
            f"validation collect {delay}",
            flush=True,
        )
        return
    print(
        f"[{profile.display_name}] schedule={schedule.kind} "
        f"rest={schedule.rest_seconds / 60:.1f}m",
        flush=True,
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
    with _profile_cycle_guard(profile, args, root_dir):
        return _run_profile_cycle_locked(profile, args, store, policy, root_dir)


@contextmanager
def _profile_cycle_guard(profile: ProfileConfig, args, root_dir: Path):
    lock_path = profile_lock_path(root_dir, profile.octo_profile_uuid)
    with FileLock(lock_path):
        try:
            yield
        finally:
            if not args.dry_run:
                _stop_octo_profile(profile, args)


def _run_profile_cycle_locked(
    profile: ProfileConfig,
    args,
    store: OrchestrationStateStore,
    policy: CalibrationPolicy,
    root_dir: Path,
) -> ProfileCycleSchedule:
    cycle_at = datetime.now(UTC).strftime("%Y%m%d_%H%M%S_%f")
    profile_root = root_dir / "profiles" / profile.storage_name
    collect_dir = profile_root / f"collect_{cycle_at}"
    collect_dir.mkdir(parents=True, exist_ok=True)
    print(f"[{profile.display_name}] collect -> {collect_dir}", flush=True)
    pipeline = _run_collection_pipeline(profile, args, collect_dir)
    collect_code = pipeline.collect_code
    observed_metrics = collect_run_metrics(
        collect_dir,
        return_code=collect_code,
        default_elapsed_seconds=args.collect_minutes * 60,
    )
    if not profile.expected_country and observed_metrics.profile_country:
        profile.expected_country = observed_metrics.profile_country
        _persist_profile_country(
            Path(args.profiles_json),
            profile.octo_profile_uuid,
            observed_metrics.profile_country,
        )
        print(
            f"[{profile.display_name}] adopted geo={observed_metrics.profile_country}",
            flush=True,
        )
    _update_calibration_pools(profile, collect_dir, root_dir)
    target_count = _count_calibration_targets(profile, collect_dir, root_dir)
    metrics = collect_run_metrics(
        collect_dir,
        expected_country=profile.expected_country,
        return_code=collect_code,
        default_elapsed_seconds=args.collect_minutes * 60,
        calibration_targets_available=target_count,
    )
    return ProfileCycleService(
        ProfileEvaluationService(store),
        store,
        ProfileCycleHooks(
            write_health=lambda decision: _write_json(
                collect_dir / "health.json",
                decision.to_dict(),
            ),
            stop_requested=_STOP_EVENT.is_set,
            execute_calibration=lambda decision, target_offset, target_limit: (
                _run_calibration(
                    profile,
                    args,
                    collect_dir,
                    root_dir,
                    decision=decision,
                    target_offset=target_offset,
                    target_limit_cap=target_limit,
                )
            ),
            log=lambda message: print(
                f"[{profile.display_name}] {message}",
                flush=True,
            ),
        ),
    ).run(
        ProfileCycleRequest(
            profile=profile,
            metrics=metrics,
            policy=policy,
            schedule_policy=_profile_schedule_policy(args),
            pipeline=pipeline,
            calibration_targets_available=target_count,
            recovery_burst_cycles=args.recovery_burst_cycles,
        )
    )


def _run_collection_pipeline(
    profile: ProfileConfig,
    args,
    collect_dir: Path,
) -> CollectionPipelineState:
    hooks = CollectionPipelineHooks(
        run_collector=lambda: _run_command(
            _collector_command(profile, args, collect_dir),
            collect_dir / "runner.log",
            timeout_seconds=args.collect_minutes * 60 + args.collect_timeout_grace,
        ),
        stop_requested=_STOP_EVENT.is_set,
        relevance_enabled=lambda: _relevance_classification_enabled(args),
        artifact_exists=lambda path: path.exists(),
        audit_interest_safety=lambda: _interest_safe_collection_violations(
            collect_dir
        ),
        record_interest_safety=lambda violations: _write_json(
            collect_dir / "interest_safety.json",
            {
                "status": "violation" if violations else "passed",
                "violations": violations,
            },
        ),
        run_classifier=lambda stage, source, include_video, log_name: _run_command(
            _relevance_classifier_command(
                collect_dir,
                stage=stage,
                source=source,
                include_video=include_video,
            ),
            collect_dir / log_name,
            timeout_seconds=args.relevance_timeout,
        ),
        run_isolated_resolver=lambda: _run_command(
            _isolated_landing_resolver_command(profile, args, collect_dir),
            collect_dir / "isolated_resolution.log",
            timeout_seconds=args.isolated_resolution_timeout,
        ),
        run_enricher=lambda source: _run_command(
            _relevant_enricher_command(
                profile,
                args,
                collect_dir,
                source=source,
            ),
            collect_dir / "enrichment.log",
            timeout_seconds=args.enrichment_timeout,
        ),
        run_backend_import=lambda source: _run_command(
            _backend_import_command(profile, source),
            collect_dir / "backend_import.log",
            timeout_seconds=args.backend_import_timeout,
        ),
        record_disabled_relevance=lambda: _write_json(
            collect_dir / "relevance_summary.json",
            {
                "status": "disabled_in_interest_safe_collection",
                "total": 0,
            },
        ),
        log=lambda message: print(f"[{profile.display_name}] {message}", flush=True),
    )
    return CollectionPipelineService(hooks).run(
        CollectionPipelineRequest(
            collect_dir=collect_dir,
            dry_run=args.dry_run,
            interest_safe_collection=args.interest_safe_collection,
            isolated_hold_resolution=args.isolated_hold_resolution,
            relevant_enrichment=args.relevant_enrichment,
            import_backend=args.import_backend,
            include_video=not args.no_video_recording,
        )
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

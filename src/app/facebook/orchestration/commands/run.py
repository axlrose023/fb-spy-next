from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import Any

from app.facebook.calibration import CalibrationPolicy
from app.facebook.profiles import Profile

from .. import (
    OrchestrationRunHooks,
    OrchestrationRunRequest,
    OrchestrationService,
    OrchestrationStateStore,
    ProfileCycleSchedule,
    ProfileScheduler,
    RecoverySchedulePolicy,
    SchedulerConfig,
    SchedulerHooks,
    profile_rest_seconds,
    recovery_schedule_policy,
    remaining_profile_rest_seconds,
    validate_orchestration_run_options,
)
from .models import RunCommandHooks
from .policy import calibration_policy_from_args


def run_command(args: Any, hooks: RunCommandHooks) -> int:
    hooks.clear_stop()
    store = hooks.state_store(Path(args.state_json))
    root_dir = Path(args.root_dir)
    policy = calibration_policy_from_args(args)
    validate_orchestration_run_options(args)
    scheduler = profile_scheduler(args, hooks, store, policy, root_dir)
    result: int = OrchestrationService(
        OrchestrationRunHooks(
            discover_profiles=lambda: hooks.discover_profiles(True),
            run_once=scheduler.run_once,
            run_continuously=scheduler.run_continuously,
        )
    ).run(OrchestrationRunRequest(continuous=args.loop))
    return result


def profile_scheduler(
    args: Any,
    hooks: RunCommandHooks,
    store: OrchestrationStateStore,
    policy: CalibrationPolicy,
    root_dir: Path,
) -> ProfileScheduler:
    schedule_policy = schedule_policy_from_args(args)
    return ProfileScheduler(
        SchedulerConfig(
            max_parallel=args.max_parallel,
            default_rest_seconds=schedule_policy.normal_rest_seconds,
            infrastructure_retry_seconds=schedule_policy.infrastructure_retry_seconds,
            discovery_interval_seconds=args.discovery_interval,
            max_cycles=args.max_cycles,
        ),
        store,
        SchedulerHooks(
            discover_profiles=lambda: hooks.discover_profiles(False),
            enabled_profiles=hooks.enabled_profiles,
            run_profile_cycle=lambda profile: hooks.run_profile_cycle(
                profile,
                store,
                policy,
                root_dir,
            ),
            remaining_profile_rest_seconds=lambda profile_uuid, rest_seconds: (
                remaining_profile_rest_seconds(
                    store.profile_last_run_at(profile_uuid),
                    rest_seconds,
                )
            ),
            log=hooks.log,
            log_schedule=lambda profile, schedule: log_profile_schedule(
                profile,
                schedule,
                burst_limit=args.recovery_burst_cycles,
                log=hooks.log,
            ),
        ),
        stop_requested=hooks.stop_requested,
        monotonic=hooks.monotonic,
        sleep=hooks.sleep,
    )


def profile_rest_seconds_from_args(args: Any) -> float:
    rest_seconds: float = profile_rest_seconds(
        cycle_sleep_seconds=args.cycle_sleep,
        profile_rest_minutes=args.profile_rest_minutes,
    )
    return rest_seconds


def schedule_policy_from_args(args: Any) -> RecoverySchedulePolicy:
    return recovery_schedule_policy(
        cycle_sleep_seconds=args.cycle_sleep,
        profile_rest_minutes=args.profile_rest_minutes,
        recovery_burst_cycles=args.recovery_burst_cycles,
        recovery_burst_rest_minutes=args.recovery_burst_rest_minutes,
        infrastructure_retry_minutes=args.infrastructure_retry_minutes,
    )


def log_profile_schedule(
    profile: Profile,
    schedule: ProfileCycleSchedule,
    *,
    burst_limit: int,
    log: Callable[[str], None] = print,
) -> None:
    if schedule.kind == "recovery_burst":
        delay = (
            "immediately"
            if schedule.rest_seconds <= 0
            else f"in {schedule.rest_seconds / 60:.1f}m"
        )
        log(
            f"[{profile.display_name}] recovery="
            f"{schedule.recovery_attempt}/{burst_limit}; "
            f"validation collect {delay}"
        )
        return
    log(
        f"[{profile.display_name}] schedule={schedule.kind} "
        f"rest={schedule.rest_seconds / 60:.1f}m"
    )

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from app.facebook.calibration import CalibrationDecision, CalibrationPolicy
from app.facebook.orchestration import (
    OrchestrationStateStore,
    ProfileCycleSchedule,
)
from app.facebook.orchestration.adapters import FileLock, profile_lock_path
from app.facebook.orchestration.commands import (
    ProfileCycleCommandHooks,
    ProfileCycleCommandRequest,
    run_profile_cycle_command,
    schedule_policy_from_args,
)
from app.facebook.profiles import Profile

from . import calibration, collection, profiles
from .context import RuntimeContext
from .files import write_json


def run_profile_cycle(
    profile: Profile,
    args: Any,
    store: OrchestrationStateStore,
    policy: CalibrationPolicy,
    root_dir: Path,
    context: RuntimeContext,
) -> ProfileCycleSchedule:
    def execute_calibration(
        cycle_profile: Profile,
        collect_dir: Path,
        cycle_root: Path,
        decision: CalibrationDecision,
        target_offset: int,
        target_limit: int,
    ) -> dict[str, Any]:
        return calibration.run_calibration(
            cycle_profile,
            args,
            collect_dir,
            cycle_root,
            context,
            decision=decision,
            target_offset=target_offset,
            target_limit_cap=target_limit,
        )

    return run_profile_cycle_command(
        ProfileCycleCommandRequest(
            profile=profile,
            state=store,
            policy=policy,
            schedule_policy=schedule_policy_from_args(args),
            root_dir=root_dir,
            collect_seconds=args.collect_minutes * 60,
            recovery_burst_cycles=args.recovery_burst_cycles,
            dry_run=args.dry_run,
        ),
        ProfileCycleCommandHooks(
            profile_lock=lambda cycle_root, profile_uuid: FileLock(
                profile_lock_path(cycle_root, profile_uuid)
            ),
            run_collection=lambda cycle_profile, collect_dir: (
                collection.run_collection_pipeline(
                    cycle_profile,
                    args,
                    collect_dir,
                    context,
                )
            ),
            persist_profile_country=lambda profile_uuid, country: (
                profiles.persist_profile_country(
                    Path(args.profiles_json),
                    profile_uuid,
                    country,
                )
            ),
            update_calibration_pools=calibration.update_calibration_pools,
            count_calibration_targets=calibration.count_calibration_targets,
            run_calibration=execute_calibration,
            stop_profile=lambda cycle_profile: profiles.stop_octo_profile(
                cycle_profile,
                args,
                context,
            ),
            write_json=write_json,
            stop_requested=context.stop_event.is_set,
            now=lambda: datetime.now(UTC),
            log=context.log,
        ),
    )

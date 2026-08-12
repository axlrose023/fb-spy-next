from __future__ import annotations

import os

from app.facebook.runs import collect_run_metrics

from .. import (
    ProfileCycleHooks,
    ProfileCycleRequest,
    ProfileCycleSchedule,
    ProfileCycleService,
    ProfileEvaluationService,
)
from .models import ProfileCycleCommandHooks, ProfileCycleCommandRequest


def run_profile_cycle_command(
    request: ProfileCycleCommandRequest,
    hooks: ProfileCycleCommandHooks,
) -> ProfileCycleSchedule:
    profile = request.profile
    with hooks.profile_lock(request.root_dir, profile.octo_profile_uuid):
        try:
            return _run_locked_profile_cycle(request, hooks)
        finally:
            if not request.dry_run:
                hooks.stop_profile(profile)


def _run_locked_profile_cycle(
    request: ProfileCycleCommandRequest,
    hooks: ProfileCycleCommandHooks,
) -> ProfileCycleSchedule:
    profile = request.profile
    cycle_at = hooks.now().strftime("%Y%m%d_%H%M%S_%f")
    collect_dir = (
        request.root_dir / "profiles" / profile.storage_name / f"collect_{cycle_at}"
    )
    collect_dir.mkdir(parents=True, exist_ok=True)
    os.chmod(collect_dir, 0o700)
    hooks.log(f"[{profile.display_name}] collect -> {collect_dir}")

    pipeline = hooks.run_collection(profile, collect_dir)
    observed_metrics = collect_run_metrics(
        collect_dir,
        return_code=pipeline.collect_code,
        default_elapsed_seconds=request.collect_seconds,
    )
    if not profile.expected_country and observed_metrics.profile_country:
        profile.expected_country = observed_metrics.profile_country
        hooks.persist_profile_country(
            profile.octo_profile_uuid,
            observed_metrics.profile_country,
        )
        hooks.log(
            f"[{profile.display_name}] adopted geo={observed_metrics.profile_country}"
        )

    hooks.update_calibration_pools(profile, collect_dir, request.root_dir)
    target_count = hooks.count_calibration_targets(
        profile,
        collect_dir,
        request.root_dir,
    )
    metrics = collect_run_metrics(
        collect_dir,
        expected_country=profile.expected_country,
        return_code=pipeline.collect_code,
        default_elapsed_seconds=request.collect_seconds,
        calibration_targets_available=target_count,
    )
    return ProfileCycleService(
        ProfileEvaluationService(request.state),
        request.state,
        ProfileCycleHooks(
            write_health=lambda decision: hooks.write_json(
                collect_dir / "health.json",
                decision.to_dict(),
            ),
            stop_requested=hooks.stop_requested,
            execute_calibration=lambda decision, target_offset, target_limit: (
                hooks.run_calibration(
                    profile,
                    collect_dir,
                    request.root_dir,
                    decision,
                    target_offset,
                    target_limit,
                )
            ),
            log=lambda message: hooks.log(f"[{profile.display_name}] {message}"),
        ),
    ).run(
        ProfileCycleRequest(
            profile=profile,
            metrics=metrics,
            policy=request.policy,
            schedule_policy=request.schedule_policy,
            pipeline=pipeline,
            calibration_targets_available=target_count,
            recovery_burst_cycles=request.recovery_burst_cycles,
        )
    )

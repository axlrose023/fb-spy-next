from __future__ import annotations

import os
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from app.facebook.calibration import (
    CalibrationDecision,
    CalibrationPassRequest,
    CalibrationPlan,
    CalibrationProcessCommandFactory,
    calibration_plan_from_options,
    calibration_timeout_seconds,
    effective_target_goal,
    persistent_target_pool,
)
from app.facebook.orchestration.commands import (
    CalibrationCommandHooks,
    run_calibration_command,
)
from app.facebook.profiles import Profile

from .context import RuntimeContext
from .files import load_json, utc_now


def run_calibration(
    profile: Profile,
    args: Any,
    collect_dir: Path,
    root_dir: Path,
    context: RuntimeContext,
    *,
    decision: CalibrationDecision,
    target_offset: int = 0,
    target_limit_cap: int | None = None,
) -> dict[str, Any]:
    commands = process_commands(context)

    def build_command(
        pass_profile: Profile,
        run_dir: Path,
        paths: list[Path],
        country: str | None,
        offset: int,
        plan: CalibrationPlan,
    ) -> list[str]:
        command: list[str] = commands.build(
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
        return command

    result: dict[str, Any] = run_calibration_command(
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
            prepare_run_dir=prepare_run_dir,
            target_sources=calibration_ads_paths,
            count_targets=count_calibration_targets,
            plan=lambda pass_decision, available: calibration_plan(
                pass_decision,
                args,
                available,
            ),
            calibrator_command=build_command,
            run_command=lambda command, log_path, timeout: context.run_command(
                command,
                log_path,
                timeout_seconds=timeout,
            ),
            timeout_seconds=lambda target_limit: timeout_seconds(
                args,
                target_limit=target_limit,
            ),
            load_json=lambda run_dir: load_json(
                run_dir / "summary.json",
                default={},
            ),
            now=utc_now,
            log=context.log,
        ),
    )
    return result


def calibrator_command(
    profile: Profile,
    args: Any,
    run_dir: Path,
    ads_paths: list[Path],
    country: str | None,
    context: RuntimeContext,
    *,
    target_offset: int = 0,
    target_limit: int | None = None,
    min_successful_targets: int | None = None,
    max_reactions: int | None = None,
    max_follows: int | None = None,
    max_comments: int | None = None,
    min_interactions: int | None = None,
) -> list[str]:
    command: list[str] = process_commands(context).build(
        profile,
        args,
        run_dir,
        ads_paths,
        country,
        target_offset=target_offset,
        target_limit=target_limit,
        min_successful_targets=min_successful_targets,
        max_reactions=max_reactions,
        max_follows=max_follows,
        max_comments=max_comments,
        min_interactions=min_interactions,
    )
    return command


def process_commands(context: RuntimeContext) -> CalibrationProcessCommandFactory:
    return CalibrationProcessCommandFactory(context.config.facebook)


def calibration_plan(
    decision: CalibrationDecision,
    args: Any,
    available_targets: int,
) -> CalibrationPlan:
    return calibration_plan_from_options(
        decision,
        args,
        available_targets=available_targets,
    )


def effective_calibration_target_goal(plan: CalibrationPlan) -> int:
    goal: int = effective_target_goal(plan)
    return goal


def prepare_run_dir(profile: Profile, root_dir: Path) -> Path:
    cycle_at = datetime.now(UTC).strftime("%Y%m%d_%H%M%S_%f")
    calibration_dir: Path = (
        root_dir / "profiles" / profile.storage_name / f"calibration_{cycle_at}"
    )
    calibration_dir.mkdir(parents=True, exist_ok=True)
    os.chmod(calibration_dir, 0o700)
    return calibration_dir


def timeout_seconds(args: Any, *, target_limit: int | None = None) -> float:
    timeout: float = calibration_timeout_seconds(args, target_limit=target_limit)
    return timeout


def count_calibration_targets(
    profile: Profile,
    collect_dir: Path,
    root_dir: Path | None = None,
) -> int:
    count: int = persistent_target_pool().count(profile, collect_dir, root_dir)
    return count


def calibration_ads_paths(
    profile: Profile,
    collect_dir: Path,
    root_dir: Path | None = None,
) -> list[Path]:
    paths: list[Path] = persistent_target_pool().source_paths(
        profile,
        collect_dir,
        root_dir,
    )
    return paths


def update_calibration_pools(
    profile: Profile,
    collect_dir: Path,
    root_dir: Path,
) -> None:
    persistent_target_pool().update(profile, collect_dir, root_dir)

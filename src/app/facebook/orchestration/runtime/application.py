from __future__ import annotations

import time
from collections.abc import Sequence
from pathlib import Path
from typing import Any

from app.facebook.orchestration.adapters import FileStateStore
from app.facebook.orchestration.commands import (
    CommandHandlers,
    EvaluateCommandRequest,
    MaintenanceCommandHooks,
    RunCommandHooks,
    SeedBaselineCommandRequest,
    dispatch,
    run_command,
    run_evaluate_command,
    run_seed_baseline_command,
)

from . import cycle, profiles
from .context import DEFAULT_CONTEXT, RuntimeContext


def main(argv: Sequence[str] | None = None) -> int:
    return run_cli(argv, context=DEFAULT_CONTEXT)


def run_cli(
    argv: Sequence[str] | None,
    *,
    context: RuntimeContext,
) -> int:
    result: int = dispatch(
        argv,
        handlers=CommandHandlers(
            run=lambda args: run(args, context),
            evaluate=lambda args: evaluate(args, context),
            seed_baseline=lambda args: seed_baseline(args, context),
            discover_active=lambda args: profiles.discover_active(args, context),
            discover_public=lambda args: profiles.discover_public(args, context),
        ),
        request_stop=context.request_stop,
    )
    return result


def run(args: Any, context: RuntimeContext) -> int:
    result: int = run_command(
        args,
        RunCommandHooks(
            clear_stop=context.stop_event.clear,
            state_store=FileStateStore,
            discover_profiles=lambda fail_fast: profiles.discover_profiles(
                args,
                context,
                fail_fast=fail_fast,
            ),
            enabled_profiles=lambda: [
                profile
                for profile in profiles.load_profiles(Path(args.profiles_json))
                if profile.enabled
            ],
            run_profile_cycle=lambda profile, store, policy, root_dir: (
                cycle.run_profile_cycle(
                    profile,
                    args,
                    store,
                    policy,
                    root_dir,
                    context,
                )
            ),
            stop_requested=context.stop_event.is_set,
            monotonic=time.monotonic,
            sleep=time.sleep,
            log=context.log,
        ),
    )
    return result


def evaluate(args: Any, context: RuntimeContext) -> int:
    result: int = run_evaluate_command(
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
        maintenance_hooks(context),
    )
    return result


def seed_baseline(args: Any, context: RuntimeContext) -> int:
    result: int = run_seed_baseline_command(
        SeedBaselineCommandRequest(
            state_path=Path(args.state_json),
            run_dir=Path(args.run_dir),
            profile_uuid=args.profile_uuid,
            label=args.label,
            expected_country=args.expected_country or None,
            default_elapsed_seconds=args.default_elapsed_seconds,
            default_scrolls=args.default_scrolls,
        ),
        maintenance_hooks(context),
    )
    return result


def maintenance_hooks(context: RuntimeContext) -> MaintenanceCommandHooks:
    return MaintenanceCommandHooks(
        state_store=FileStateStore,
        output=context.output,
    )

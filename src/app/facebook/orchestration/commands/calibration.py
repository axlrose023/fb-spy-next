from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from app.facebook.calibration import (
    CalibrationDecision,
    CalibrationPassHooks,
    CalibrationPassRequest,
    CalibrationPassService,
    CalibrationPlan,
)
from app.facebook.profiles import Profile
from app.facebook.runs import collect_run_metrics

CalibrationCommandBuilder = Callable[
    [Profile, Path, list[Path], str | None, int, CalibrationPlan],
    list[str],
]


@dataclass(frozen=True, slots=True)
class CalibrationCommandHooks:
    prepare_run_dir: Callable[[Profile, Path], Path]
    target_sources: Callable[[Profile, Path, Path], list[Path]]
    count_targets: Callable[[Profile, Path, Path], int]
    plan: Callable[[CalibrationDecision, int], CalibrationPlan]
    calibrator_command: CalibrationCommandBuilder
    run_command: Callable[[list[str], Path, float], int]
    timeout_seconds: Callable[[int | None], float]
    load_json: Callable[[Path], dict[str, Any]]
    now: Callable[[], str]
    log: Callable[[str], None]


def run_calibration_command(
    request: CalibrationPassRequest,
    hooks: CalibrationCommandHooks,
) -> dict[str, Any]:
    pass_hooks = CalibrationPassHooks(
        prepare_run_dir=hooks.prepare_run_dir,
        target_sources=hooks.target_sources,
        count_targets=hooks.count_targets,
        plan=hooks.plan,
        observe_country=lambda profile, run_dir, elapsed: (
            collect_run_metrics(
                run_dir,
                expected_country=profile.expected_country,
                default_elapsed_seconds=elapsed,
            ).profile_country
            or profile.expected_country
        ),
        execute=lambda profile, run_dir, paths, country, offset, plan: (
            hooks.run_command(
                hooks.calibrator_command(
                    profile,
                    run_dir,
                    paths,
                    country,
                    offset,
                    plan,
                ),
                run_dir / "calibrator.log",
                hooks.timeout_seconds(plan.target_limit),
            )
        ),
        load_summary=hooks.load_json,
        now=hooks.now,
        log=hooks.log,
    )
    record: dict[str, Any] = CalibrationPassService(pass_hooks).run(request)
    return record

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from app.facebook.profiles import Profile

from ..models import CalibrationDecision, CalibrationPlan
from .pass_outcome import build_calibration_pass_record

PrepareRunDirectory = Callable[[Profile, Path], Path]
TargetSources = Callable[[Profile, Path, Path], list[Path]]
TargetCounter = Callable[[Profile, Path, Path], int]
PassPlanner = Callable[[CalibrationDecision, int], CalibrationPlan]
CountryObserver = Callable[[Profile, Path, float], str | None]
PassExecutor = Callable[
    [Profile, Path, list[Path], str | None, int, CalibrationPlan],
    int,
]
SummaryLoader = Callable[[Path], dict[str, Any]]


@dataclass(frozen=True, slots=True)
class CalibrationPassRequest:
    profile: Profile
    collect_dir: Path
    root_dir: Path
    decision: CalibrationDecision
    default_elapsed_seconds: float
    dry_run: bool
    target_offset: int = 0
    target_limit_cap: int | None = None


@dataclass(frozen=True, slots=True)
class CalibrationPassHooks:
    prepare_run_dir: PrepareRunDirectory
    target_sources: TargetSources
    count_targets: TargetCounter
    plan: PassPlanner
    observe_country: CountryObserver
    execute: PassExecutor
    load_summary: SummaryLoader
    now: Callable[[], str]
    log: Callable[[str], None]


class CalibrationPassService:
    def __init__(self, hooks: CalibrationPassHooks) -> None:
        self._hooks = hooks

    def run(self, request: CalibrationPassRequest) -> dict[str, Any]:
        profile = request.profile
        run_dir = self._hooks.prepare_run_dir(profile, request.root_dir)
        ads_paths = self._hooks.target_sources(
            profile,
            request.collect_dir,
            request.root_dir,
        )
        targets_available = self._hooks.count_targets(
            profile,
            request.collect_dir,
            request.root_dir,
        )
        pass_targets_available = targets_available
        if request.target_limit_cap is not None:
            pass_targets_available = min(
                pass_targets_available,
                max(0, request.target_limit_cap),
            )
        plan = self._hooks.plan(request.decision, pass_targets_available)
        country = self._hooks.observe_country(
            profile,
            request.collect_dir,
            request.default_elapsed_seconds,
        )
        self._hooks.log(
            f"[{profile.display_name}] calibration -> {run_dir} "
            f"targets_from={len(ads_paths)} available={targets_available} "
            f"pass_available={pass_targets_available} tier={plan.tier} "
            f"limit={plan.target_limit} goal={plan.target_goal}"
        )
        return_code = 0
        if not request.dry_run:
            return_code = self._hooks.execute(
                profile,
                run_dir,
                ads_paths,
                country,
                request.target_offset,
                plan,
            )
        summary = self._hooks.load_summary(run_dir)
        record: dict[str, Any] = build_calibration_pass_record(
            run_dir=run_dir,
            return_code=return_code,
            summary=summary,
            ads_paths=ads_paths,
            plan=plan,
            targets_available=targets_available,
            pass_targets_available=pass_targets_available,
            now=self._hooks.now,
        )
        return record

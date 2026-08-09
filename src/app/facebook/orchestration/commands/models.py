from __future__ import annotations

import argparse
from collections.abc import Callable
from contextlib import AbstractContextManager
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

from app.facebook.calibration import CalibrationDecision, CalibrationPolicy
from app.facebook.profiles import Profile

from ..contracts import OrchestrationStateStore
from ..lifecycle import CollectionPipelineState
from ..models import ProfileCycleSchedule, RecoverySchedulePolicy

CommandHandler = Callable[[argparse.Namespace], int]


@dataclass(frozen=True, slots=True)
class CommandHandlers:
    run: CommandHandler
    evaluate: CommandHandler
    seed_baseline: CommandHandler
    discover_active: CommandHandler
    discover_public: CommandHandler


@dataclass(frozen=True, slots=True)
class RunCommandHooks:
    clear_stop: Callable[[], None]
    state_store: Callable[[Path], OrchestrationStateStore]
    discover_profiles: Callable[[bool], None]
    enabled_profiles: Callable[[], list[Profile]]
    run_profile_cycle: Callable[
        [Profile, OrchestrationStateStore, CalibrationPolicy, Path],
        ProfileCycleSchedule | None,
    ]
    stop_requested: Callable[[], bool]
    monotonic: Callable[[], float]
    sleep: Callable[[float], None]
    log: Callable[[str], None]


@dataclass(frozen=True, slots=True)
class ProfileCycleCommandRequest:
    profile: Profile
    state: OrchestrationStateStore
    policy: CalibrationPolicy
    schedule_policy: RecoverySchedulePolicy
    root_dir: Path
    collect_seconds: float
    recovery_burst_cycles: int
    dry_run: bool


@dataclass(frozen=True, slots=True)
class ProfileCycleCommandHooks:
    profile_lock: Callable[[Path, str], AbstractContextManager[Any]]
    run_collection: Callable[[Profile, Path], CollectionPipelineState]
    persist_profile_country: Callable[[str, str], None]
    update_calibration_pools: Callable[[Profile, Path, Path], None]
    count_calibration_targets: Callable[[Profile, Path, Path], int]
    run_calibration: Callable[
        [Profile, Path, Path, CalibrationDecision, int, int],
        dict[str, Any],
    ]
    stop_profile: Callable[[Profile], None]
    write_json: Callable[[Path, Any], None]
    stop_requested: Callable[[], bool]
    now: Callable[[], datetime]
    log: Callable[[str], None]

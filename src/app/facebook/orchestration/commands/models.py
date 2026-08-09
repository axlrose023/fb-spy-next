from __future__ import annotations

import argparse
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from app.facebook.calibration import CalibrationPolicy
from app.facebook.profiles import Profile

from ..contracts import OrchestrationStateStore
from ..models import ProfileCycleSchedule

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

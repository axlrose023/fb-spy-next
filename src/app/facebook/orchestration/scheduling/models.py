from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from app.facebook.profiles import Profile

from ..models import ProfileCycleSchedule


@dataclass(frozen=True, slots=True)
class SchedulerConfig:
    max_parallel: int
    default_rest_seconds: float
    infrastructure_retry_seconds: float
    discovery_interval_seconds: float
    max_cycles: int = 0
    poll_interval_seconds: float = 1.0


@dataclass(frozen=True, slots=True)
class SchedulerHooks:
    discover_profiles: Callable[[], None]
    enabled_profiles: Callable[[], list[Profile]]
    run_profile_cycle: Callable[[Profile], ProfileCycleSchedule | None]
    remaining_profile_rest_seconds: Callable[[str, float], float]
    log: Callable[[str], None]
    log_schedule: Callable[[Profile, ProfileCycleSchedule], None]

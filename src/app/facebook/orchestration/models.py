from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True, slots=True)
class RecoverySchedulePolicy:
    normal_rest_seconds: float
    burst_limit: int
    burst_rest_seconds: float
    infrastructure_retry_seconds: float


@dataclass(frozen=True, slots=True)
class ProfileCycleSchedule:
    kind: str
    rest_seconds: float
    recovery_burst_count: int = 0
    recovery_attempt: int | None = None
    recovery_active: bool = False


@dataclass(frozen=True, slots=True)
class ProfileState:
    octo_profile_uuid: str = ""
    label: str = ""
    expected_country: str | None = None
    runs: tuple[dict[str, Any], ...] = ()
    calibrations: tuple[dict[str, Any], ...] = ()
    recovery_burst_count: int = 0
    last_schedule: ProfileCycleSchedule | None = None
    baseline: dict[str, Any] | None = None
    updated_at: str | None = None
    extras: dict[str, Any] = field(default_factory=dict)

    @property
    def recovery_active(self) -> bool:
        if self.recovery_burst_count > 0:
            return True
        schedule = self.last_schedule
        return bool(
            schedule
            and (
                schedule.recovery_active
                or schedule.kind in {"recovery_burst", "recovery_burst_rest"}
            )
        )


@dataclass(frozen=True, slots=True)
class OrchestrationState:
    profiles: dict[str, ProfileState] = field(default_factory=dict)
    extras: dict[str, Any] = field(default_factory=dict)

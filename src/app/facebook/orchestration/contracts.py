from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path
from typing import Any, Protocol

from app.facebook.calibration import CalibrationDecision, CalibrationPolicy
from app.facebook.profiles import MetricBaseline, Profile
from app.facebook.runs import RunMetrics

from .models import ProfileCycleSchedule, RecoverySchedulePolicy


class ProfileStateReader(Protocol):
    def profile_history(
        self,
        profile_uuid: str,
    ) -> tuple[list[RunMetrics], MetricBaseline, list[str]]: ...

    def profile_calibration_attempts(self, profile_uuid: str) -> list[str]: ...

    def profile_calibration_target_offset(self, profile_uuid: str) -> int: ...

    def profile_last_run_at(self, profile_uuid: str) -> str | None: ...

    def profile_recovery_burst_count(self, profile_uuid: str) -> int: ...

    def profile_recovery_evaluation_active(self, profile_uuid: str) -> bool: ...

    def profile_resume_schedule(
        self,
        profile_uuid: str,
        *,
        default_rest_seconds: float,
    ) -> ProfileCycleSchedule: ...


class ProfileStateWriter(Protocol):
    def record_profile_run(
        self,
        profile: Profile,
        metrics: RunMetrics,
        decision: CalibrationDecision,
        *,
        calibration: dict[str, Any] | None = None,
        calibrations: list[dict[str, Any]] | None = None,
        policy: CalibrationPolicy,
        schedule_policy: RecoverySchedulePolicy | None = None,
        infrastructure_retry_required: bool = False,
    ) -> ProfileCycleSchedule: ...

    def seed_baseline(
        self,
        profile_uuid: str,
        metrics: RunMetrics,
        *,
        label: str = "",
        expected_country: str | None = None,
        policy: CalibrationPolicy,
    ) -> MetricBaseline: ...


class OrchestrationStateStore(ProfileStateReader, ProfileStateWriter, Protocol):
    pass


class CommandRunner(Protocol):
    def run(
        self,
        command: Sequence[str],
        log_path: Path,
        *,
        timeout_seconds: float | None = None,
        interrupt_grace_seconds: float = 30.0,
    ) -> int: ...

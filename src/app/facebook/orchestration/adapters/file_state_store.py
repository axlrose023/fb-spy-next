from __future__ import annotations

import fcntl
import json
import os
import threading
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, cast

from app.facebook.calibration import (
    CalibrationDecision,
    CalibrationPolicy,
    is_good_baseline_candidate,
    metrics_from_dict,
)
from app.facebook.profiles import MetricBaseline, Profile
from app.facebook.runs import RunMetrics

from ..lifecycle import (
    baseline_from_run_records,
    calibration_timestamp,
    calibration_was_effective,
    is_healthy_relevance_result,
    new_profile_state,
)
from ..models import ProfileCycleSchedule, RecoverySchedulePolicy
from ..scheduling import next_profile_schedule
from ..serialization import (
    profile_resume_schedule,
    profile_state_recovery_active,
    schedule_to_dict,
    to_nonnegative_int,
)

DEFAULT_SCHEDULE_POLICY = RecoverySchedulePolicy(
    normal_rest_seconds=0.0,
    burst_limit=3,
    burst_rest_seconds=0.0,
    infrastructure_retry_seconds=300.0,
)


class FileStateStore:
    def __init__(
        self,
        path: Path,
        *,
        clock: Callable[[], str] | None = None,
    ) -> None:
        self.path = path
        self._clock = clock or _utc_now
        self._lock = threading.Lock()

    @contextmanager
    def _process_lock(self) -> Iterator[None]:
        lock_path = self.path.with_suffix(self.path.suffix + ".lock")
        lock_path.parent.mkdir(parents=True, exist_ok=True)
        fd = os.open(lock_path, os.O_CREAT | os.O_RDWR, 0o644)
        try:
            fcntl.flock(fd, fcntl.LOCK_EX)
            yield
        finally:
            fcntl.flock(fd, fcntl.LOCK_UN)
            os.close(fd)

    def load(self) -> dict[str, Any]:
        if not self.path.exists():
            return {"profiles": {}}
        try:
            return cast(
                dict[str, Any],
                json.loads(self.path.read_text(encoding="utf-8")),
            )
        except (OSError, json.JSONDecodeError):
            return {"profiles": {}}

    def save(self, state: dict[str, Any]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(self.path.suffix + ".tmp")
        tmp.write_text(
            json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        tmp.replace(self.path)

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
    ) -> ProfileCycleSchedule:
        with self._lock, self._process_lock():
            state = self.load()
            profile_state = state.setdefault("profiles", {}).setdefault(
                profile.octo_profile_uuid,
                new_profile_state(profile),
            )
            profile_state["label"] = profile.label
            profile_state["expected_country"] = profile.expected_country
            runs = profile_state.setdefault("runs", [])
            baseline_candidate = is_good_baseline_candidate(metrics, policy) and (
                decision.baseline.sample_count < policy.baseline_min_samples
                or decision.status == "healthy"
            )
            trusted_baseline = (
                profile.quality_guard
                and not decision.baseline.trusted
                and baseline_candidate
                and is_healthy_relevance_result(metrics, policy)
            )
            runs.append(
                {
                    "at": self._clock(),
                    "run_dir": metrics.run_dir,
                    "baseline_candidate": baseline_candidate,
                    "trusted_baseline": trusted_baseline,
                    "metrics": metrics.to_dict(),
                    "decision": decision.to_dict(),
                }
            )
            del runs[:-100]
            calibration_records = list(calibrations or [])
            if calibration and not calibration_records:
                calibration_records.append(calibration)
            if calibration_records:
                stored_calibrations = profile_state.setdefault("calibrations", [])
                stored_calibrations.extend(calibration_records)
                del stored_calibrations[:-100]
            last_calibration = (
                calibration_records[-1] if calibration_records else calibration
            )
            schedule = next_profile_schedule(
                previous_burst_count=to_nonnegative_int(
                    profile_state.get("recovery_burst_count")
                ),
                previous_recovery_active=profile_state_recovery_active(profile_state),
                metrics=metrics,
                decision=decision,
                calibration=last_calibration,
                infrastructure_retry_required=infrastructure_retry_required,
                policy=schedule_policy or DEFAULT_SCHEDULE_POLICY,
            )
            profile_state["recovery_burst_count"] = schedule.recovery_burst_count
            profile_state["last_schedule"] = schedule_to_dict(schedule)
            profile_state["baseline"] = baseline_from_run_records(
                runs, policy
            ).to_dict()
            profile_state["updated_at"] = self._clock()
            self.save(state)
            return schedule

    def seed_baseline(
        self,
        profile_uuid: str,
        metrics: RunMetrics,
        *,
        label: str = "",
        expected_country: str | None = None,
        policy: CalibrationPolicy,
    ) -> MetricBaseline:
        with self._lock, self._process_lock():
            state = self.load()
            profile_state = state.setdefault("profiles", {}).setdefault(
                profile_uuid,
                {
                    "octo_profile_uuid": profile_uuid,
                    "label": label,
                    "expected_country": expected_country,
                    "runs": [],
                    "calibrations": [],
                },
            )
            runs = profile_state.setdefault("runs", [])
            runs.append(
                {
                    "at": self._clock(),
                    "run_dir": metrics.run_dir,
                    "seed_baseline": True,
                    "baseline_candidate": True,
                    "metrics": metrics.to_dict(),
                }
            )
            del runs[:-100]
            baseline = baseline_from_run_records(runs, policy)
            profile_state["baseline"] = baseline.to_dict()
            profile_state["updated_at"] = self._clock()
            self.save(state)
            return baseline

    def profile_history(
        self, profile_uuid: str
    ) -> tuple[list[RunMetrics], MetricBaseline, list[str]]:
        with self._lock, self._process_lock():
            profile_state = self._profile_state(profile_uuid)
            runs = [
                metrics_from_dict(item["metrics"])
                for item in profile_state.get("runs", [])
                if isinstance(item.get("metrics"), dict)
                and not item.get("seed_baseline")
            ]
            baseline = MetricBaseline.from_dict(profile_state.get("baseline"))
            calibrations = [
                str(calibration_timestamp(item))
                for item in profile_state.get("calibrations", [])
                if calibration_was_effective(item) and calibration_timestamp(item)
            ]
            return runs, baseline, calibrations

    def profile_calibration_attempts(self, profile_uuid: str) -> list[str]:
        with self._lock, self._process_lock():
            profile_state = self._profile_state(profile_uuid)
            return [
                str(calibration_timestamp(item))
                for item in profile_state.get("calibrations", [])
                if calibration_timestamp(item)
            ]

    def profile_calibration_target_offset(self, profile_uuid: str) -> int:
        with self._lock, self._process_lock():
            profile_state = self._profile_state(profile_uuid)
            consumed = 0
            for item in profile_state.get("calibrations", []):
                summary = (
                    item.get("summary") if isinstance(item.get("summary"), dict) else {}
                )
                value = (
                    summary.get("visited")
                    or item.get("target_limit")
                    or item.get("target_goal")
                    or CalibrationPolicy().min_successful_calibration_targets
                )
                try:
                    consumed += max(1, int(value))
                except (TypeError, ValueError):
                    consumed += CalibrationPolicy().min_successful_calibration_targets
            return consumed

    def profile_last_run_at(self, profile_uuid: str) -> str | None:
        with self._lock, self._process_lock():
            profile_state = self._profile_state(profile_uuid)
            for item in reversed(profile_state.get("runs", [])):
                if item.get("seed_baseline"):
                    continue
                value = item.get("at")
                if not value and isinstance(item.get("metrics"), dict):
                    value = item["metrics"].get("finished_at")
                if value:
                    return str(value)
            return None

    def profile_recovery_burst_count(self, profile_uuid: str) -> int:
        with self._lock, self._process_lock():
            return int(
                to_nonnegative_int(
                    self._profile_state(profile_uuid).get("recovery_burst_count")
                )
            )

    def profile_recovery_evaluation_active(self, profile_uuid: str) -> bool:
        with self._lock, self._process_lock():
            return bool(
                profile_state_recovery_active(self._profile_state(profile_uuid))
            )

    def profile_resume_schedule(
        self,
        profile_uuid: str,
        *,
        default_rest_seconds: float,
    ) -> ProfileCycleSchedule:
        with self._lock, self._process_lock():
            return profile_resume_schedule(
                self._profile_state(profile_uuid),
                default_rest_seconds=default_rest_seconds,
            )

    def _profile_state(self, profile_uuid: str) -> dict[str, Any]:
        return cast(
            dict[str, Any],
            self.load().get("profiles", {}).get(profile_uuid, {}),
        )


def _utc_now() -> str:
    return datetime.now(UTC).isoformat()

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from app.facebook.calibration import CalibrationDecision, CalibrationPolicy
from app.facebook.orchestration import ProfileCycleSchedule, ProfileEvaluationService
from app.facebook.profiles import MetricBaseline
from app.facebook.runs import RunMetrics

pytestmark = pytest.mark.unit


def baseline_run(run_dir: str) -> RunMetrics:
    return RunMetrics(
        run_dir=run_dir,
        return_code=0,
        elapsed_seconds=900,
        scrolls=100,
        ads_total=20,
        target_ads=10,
        geo_observed=True,
        geo_match=True,
        ads_per_hour=80,
        target_per_hour=40,
    )


class EvaluationState:
    def __init__(
        self,
        *,
        history: list[RunMetrics],
        baseline: MetricBaseline,
        calibrations: list[str] | None = None,
        attempts: list[str] | None = None,
    ) -> None:
        self.history = history
        self.baseline = baseline
        self.calibrations = calibrations or []
        self.attempts = attempts or []
        self.calls: list[str] = []

    def profile_history(
        self,
        _profile_uuid: str,
    ) -> tuple[list[RunMetrics], MetricBaseline, list[str]]:
        self.calls.append("history")
        return list(self.history), self.baseline, list(self.calibrations)

    def profile_calibration_attempts(self, _profile_uuid: str) -> list[str]:
        self.calls.append("attempts")
        return list(self.attempts)

    def profile_calibration_target_offset(self, _profile_uuid: str) -> int:
        self.calls.append("offset")
        return 30

    def profile_last_run_at(self, _profile_uuid: str) -> str | None:
        return None

    def profile_recovery_burst_count(self, _profile_uuid: str) -> int:
        self.calls.append("recovery_count")
        return 2

    def profile_recovery_evaluation_active(self, _profile_uuid: str) -> bool:
        self.calls.append("recovery_active")
        return True

    def profile_resume_schedule(
        self,
        _profile_uuid: str,
        *,
        default_rest_seconds: float,
    ) -> ProfileCycleSchedule:
        return ProfileCycleSchedule(kind="normal", rest_seconds=default_rest_seconds)


def test_profile_cycle_evaluation_loads_recovery_context_and_policy(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    state = EvaluationState(
        history=[baseline_run("previous")],
        baseline=MetricBaseline(),
        calibrations=["2026-08-09T10:00:00+00:00"],
        attempts=["2026-08-09T11:00:00+00:00"],
    )
    captured: dict[str, Any] = {}

    def capture_decision(
        metrics: RunMetrics,
        **kwargs: Any,
    ) -> CalibrationDecision:
        captured["metrics"] = metrics
        captured.update(kwargs)
        return CalibrationDecision(
            status="calibrate",
            should_calibrate=True,
            severity="high",
        )

    monkeypatch.setattr(
        "app.facebook.orchestration.lifecycle.evaluation.evaluate_calibration_need",
        capture_decision,
    )
    current = baseline_run("current")

    result = ProfileEvaluationService(state).evaluate(
        "profile",
        current,
        CalibrationPolicy(calibration_cooldown_seconds=3600),
        quality_guard=True,
    )

    evaluation_policy = captured["policy"]
    assert evaluation_policy.calibration_cooldown_seconds == 0
    assert evaluation_policy.proactive_quality_drop_enabled is True
    assert captured["last_calibration_at"] == "2026-08-09T10:00:00+00:00"
    assert result.recovery_burst_count == 2
    assert result.recovery_active is True
    assert result.calibration_target_offset == 30
    assert result.baseline.source_run_dirs == ["previous"]
    assert state.calls == [
        "history",
        "recovery_count",
        "recovery_active",
        "attempts",
        "offset",
    ]


def test_cli_evaluation_excludes_current_run_and_skips_recovery_reads(
    tmp_path: Path,
) -> None:
    current_dir = tmp_path / "current"
    previous_dir = tmp_path / "previous"
    current = baseline_run(str(current_dir))
    previous = baseline_run(str(previous_dir))
    state = EvaluationState(
        history=[previous, current],
        baseline=MetricBaseline(
            sample_count=2,
            source_run_dirs=[str(previous_dir), str(current_dir)],
        ),
    )

    result = ProfileEvaluationService(state).evaluate(
        "profile",
        current,
        CalibrationPolicy(),
        load_recovery_context=False,
        exclude_run_dir=str(current_dir),
    )

    assert [item.run_dir for item in result.history] == [str(previous_dir)]
    assert result.baseline.source_run_dirs == [str(previous_dir)]
    assert result.recovery_burst_count == 0
    assert result.recovery_active is False
    assert result.calibration_target_offset == 0
    assert state.calls == ["history", "attempts"]


def test_existing_baseline_is_preserved_when_no_run_is_excluded() -> None:
    baseline = MetricBaseline(
        sample_count=3,
        source_run_dirs=["one", "two", "three"],
    )
    state = EvaluationState(history=[], baseline=baseline)

    result = ProfileEvaluationService(state).evaluate(
        "profile",
        RunMetrics(run_dir="current"),
        CalibrationPolicy(),
        load_recovery_context=False,
    )

    assert result.baseline == baseline

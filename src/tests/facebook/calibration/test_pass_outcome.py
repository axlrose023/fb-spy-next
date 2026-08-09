from __future__ import annotations

from pathlib import Path

import pytest

from app.facebook.calibration import CalibrationPlan, build_calibration_pass_record

pytestmark = pytest.mark.unit


class Clock:
    def __init__(self) -> None:
        self.calls = 0

    def __call__(self) -> str:
        self.calls += 1
        return f"clock-{self.calls}"


def plan(*, tier: str = "standard", limit: int = 10, goal: int = 3) -> CalibrationPlan:
    return CalibrationPlan(
        tier=tier,
        target_limit=limit,
        target_goal=goal,
        max_reactions=6,
        max_follows=2,
        max_comments=1,
        min_interactions=3,
    )


def test_completed_pass_preserves_record_shape_and_finished_timestamp(
    tmp_path: Path,
) -> None:
    clock = Clock()
    summary = {
        "status": "completed",
        "ok": 3,
        "interaction_goal_met": True,
        "started_at": "started",
        "finished_at": "finished",
    }
    ads_paths = [tmp_path / "first.json", tmp_path / "second.json"]

    record = build_calibration_pass_record(
        run_dir=tmp_path / "calibration",
        return_code=0,
        summary=summary,
        ads_paths=ads_paths,
        plan=plan(),
        targets_available=20,
        pass_targets_available=10,
        now=clock,
    )

    assert record == {
        "at": "clock-1",
        "run_dir": str(tmp_path / "calibration"),
        "return_code": 0,
        "summary": summary,
        "started_at": "started",
        "finished_at": "finished",
        "ads_json": [str(path) for path in ads_paths],
        "effective": True,
        "successful_targets": 3,
        "tier": "standard",
        "target_limit": 10,
        "targets_available": 20,
        "pass_targets_available": 10,
        "target_goal": 3,
        "effective_target_goal": 3,
        "interaction_limits": {
            "max_reactions": 6,
            "max_follows": 2,
            "max_comments": 1,
            "min_interactions": 3,
        },
    }
    assert clock.calls == 1


def test_missing_finished_timestamp_uses_second_clock_read() -> None:
    clock = Clock()

    record = build_calibration_pass_record(
        run_dir=Path("calibration"),
        return_code=2,
        summary={"status": "failed", "ok": "16", "interaction_goal_met": True},
        ads_paths=[],
        plan=plan(tier="recovery", limit=27, goal=27),
        targets_available=50,
        pass_targets_available=27,
        now=clock,
    )

    assert record["at"] == "clock-1"
    assert record["finished_at"] == "clock-2"
    assert record["successful_targets"] == 16
    assert record["effective_target_goal"] == 17
    assert record["effective"] is False
    assert clock.calls == 2


def test_interaction_goal_must_be_literal_true() -> None:
    record = build_calibration_pass_record(
        run_dir=Path("calibration"),
        return_code=0,
        summary={
            "status": "completed",
            "ok": 3,
            "interaction_goal_met": 1,
            "finished_at": "finished",
        },
        ads_paths=[],
        plan=plan(),
        targets_available=3,
        pass_targets_available=3,
        now=lambda: "now",
    )

    assert record["effective"] is False

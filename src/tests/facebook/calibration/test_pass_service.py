from __future__ import annotations

from pathlib import Path
from typing import Any
from unittest.mock import ANY

import pytest

from app.facebook.calibration import (
    CalibrationDecision,
    CalibrationPassHooks,
    CalibrationPassRequest,
    CalibrationPassService,
    CalibrationPlan,
)
from app.facebook.profiles import Profile

pytestmark = pytest.mark.unit


class PassHarness:
    def __init__(self, tmp_path: Path) -> None:
        self.tmp_path = tmp_path
        self.calls: list[str] = []
        self.execute_args: tuple[Any, ...] | None = None

    def prepare(self, _profile: Profile, _root_dir: Path) -> Path:
        self.calls.append("prepare")
        return self.tmp_path / "calibration"

    def sources(
        self,
        _profile: Profile,
        _collect_dir: Path,
        _root_dir: Path,
    ) -> list[Path]:
        self.calls.append("sources")
        return [self.tmp_path / "first.json", self.tmp_path / "second.json"]

    def count(self, _profile: Profile, _collect: Path, _root: Path) -> int:
        self.calls.append("count")
        return 50

    def plan(self, _decision: CalibrationDecision, available: int) -> CalibrationPlan:
        self.calls.append(f"plan:{available}")
        return CalibrationPlan(
            tier="recovery",
            target_limit=available,
            target_goal=10,
            max_reactions=6,
            max_follows=2,
            max_comments=0,
            min_interactions=1,
        )

    def country(self, _profile: Profile, _collect: Path, elapsed: float) -> str:
        self.calls.append(f"country:{elapsed}")
        return "Spain"

    def execute(self, *args: Any) -> int:
        self.calls.append("execute")
        self.execute_args = args
        return 7

    def summary(self, _run_dir: Path) -> dict[str, Any]:
        self.calls.append("summary")
        return {
            "status": "completed",
            "ok": 10,
            "interaction_goal_met": True,
            "finished_at": "finished",
        }

    def now(self) -> str:
        self.calls.append("now")
        return "now"

    def log(self, message: str) -> None:
        self.calls.append(f"log:{message}")

    def hooks(self) -> CalibrationPassHooks:
        return CalibrationPassHooks(
            prepare_run_dir=self.prepare,
            target_sources=self.sources,
            count_targets=self.count,
            plan=self.plan,
            observe_country=self.country,
            execute=self.execute,
            load_summary=self.summary,
            now=self.now,
            log=self.log,
        )


def request(tmp_path: Path, *, dry_run: bool = False) -> CalibrationPassRequest:
    return CalibrationPassRequest(
        profile=Profile("profile", label="Spain"),
        collect_dir=tmp_path / "collect",
        root_dir=tmp_path / "root",
        decision=CalibrationDecision(
            status="calibrate",
            should_calibrate=True,
            severity="high",
        ),
        default_elapsed_seconds=900,
        dry_run=dry_run,
        target_offset=11,
        target_limit_cap=7,
    )


def test_pass_service_preserves_sequence_cap_and_execution_inputs(
    tmp_path: Path,
) -> None:
    harness = PassHarness(tmp_path)

    record = CalibrationPassService(harness.hooks()).run(request(tmp_path))

    assert harness.calls == [
        "prepare",
        "sources",
        "count",
        "plan:7",
        "country:900",
        (
            f"log:[Spain] calibration -> {tmp_path / 'calibration'} "
            "targets_from=2 available=50 pass_available=7 tier=recovery "
            "limit=7 goal=10"
        ),
        "execute",
        "summary",
        "now",
    ]
    assert harness.execute_args is not None
    assert harness.execute_args[3:] == ("Spain", 11, ANY)
    assert record["return_code"] == 7
    assert record["targets_available"] == 50
    assert record["pass_targets_available"] == 7


def test_dry_run_skips_process_but_still_records_artifacts(tmp_path: Path) -> None:
    harness = PassHarness(tmp_path)

    record = CalibrationPassService(harness.hooks()).run(
        request(tmp_path, dry_run=True)
    )

    assert "execute" not in harness.calls
    assert record["return_code"] == 0
    assert record["summary"]["status"] == "completed"


def test_missing_cap_uses_all_available_targets(tmp_path: Path) -> None:
    harness = PassHarness(tmp_path)
    pass_request = request(tmp_path)
    pass_request = CalibrationPassRequest(
        profile=pass_request.profile,
        collect_dir=pass_request.collect_dir,
        root_dir=pass_request.root_dir,
        decision=pass_request.decision,
        default_elapsed_seconds=pass_request.default_elapsed_seconds,
        dry_run=pass_request.dry_run,
        target_offset=pass_request.target_offset,
        target_limit_cap=None,
    )

    record = CalibrationPassService(harness.hooks()).run(pass_request)

    assert "plan:50" in harness.calls
    assert record["pass_targets_available"] == 50

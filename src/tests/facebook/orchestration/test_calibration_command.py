from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from app.facebook.calibration import (
    CalibrationDecision,
    CalibrationPassRequest,
    CalibrationPlan,
)
from app.facebook.orchestration.commands import (
    CalibrationCommandHooks,
    run_calibration_command,
)
from app.facebook.profiles import Profile

pytestmark = pytest.mark.unit


def test_calibration_command_wires_capped_pass_and_summary(tmp_path: Path) -> None:
    collect_dir = tmp_path / "collect"
    collect_dir.mkdir()
    (collect_dir / "run_meta.json").write_text(
        json.dumps({"profile_country": "Canada"}),
        encoding="utf-8",
    )
    (collect_dir / "ads.json").write_text("[]", encoding="utf-8")
    profile = Profile(octo_profile_uuid="profile", label="canada")
    decision = CalibrationDecision(
        status="calibrate",
        should_calibrate=True,
        severity="high",
        reasons=["low_relevance"],
    )
    plan = CalibrationPlan(
        tier="deep",
        target_limit=7,
        target_goal=3,
        max_reactions=4,
        max_follows=2,
        max_comments=0,
        min_interactions=3,
    )
    events: list[Any] = []
    source = tmp_path / "targets.json"

    def prepare_run_dir(_profile: Profile, root_dir: Path) -> Path:
        run_dir = root_dir / "calibration"
        run_dir.mkdir(parents=True)
        return run_dir

    def choose_plan(
        pass_decision: CalibrationDecision,
        available: int,
    ) -> CalibrationPlan:
        events.append(("plan", pass_decision, available))
        return plan

    def calibrator_command(
        pass_profile: Profile,
        run_dir: Path,
        paths: list[Path],
        country: str | None,
        offset: int,
        pass_plan: CalibrationPlan,
    ) -> list[str]:
        events.append(
            (
                "builder",
                pass_profile,
                run_dir,
                paths,
                country,
                offset,
                pass_plan,
            )
        )
        return ["calibrate"]

    def run_command(command: list[str], log_path: Path, timeout: float) -> int:
        events.append(("execute", command, log_path.name, timeout))
        (log_path.parent / "summary.json").write_text(
            json.dumps({"status": "completed", "visited": 7, "ok": 7}),
            encoding="utf-8",
        )
        return 0

    record = run_calibration_command(
        CalibrationPassRequest(
            profile=profile,
            collect_dir=collect_dir,
            root_dir=tmp_path / "root",
            decision=decision,
            default_elapsed_seconds=600,
            dry_run=False,
            target_offset=11,
            target_limit_cap=7,
        ),
        CalibrationCommandHooks(
            prepare_run_dir=prepare_run_dir,
            target_sources=lambda *_args: [source],
            count_targets=lambda *_args: 20,
            plan=choose_plan,
            calibrator_command=calibrator_command,
            run_command=run_command,
            timeout_seconds=lambda target_limit: 92 + int(target_limit or 0),
            load_json=lambda run_dir: json.loads(
                (run_dir / "summary.json").read_text(encoding="utf-8")
            ),
            now=lambda: "2026-08-09T12:00:00+00:00",
            log=lambda message: events.append(("log", message)),
        ),
    )

    assert events[0] == ("plan", decision, 7)
    assert events[1][0] == "log"
    assert events[2] == (
        "builder",
        profile,
        tmp_path / "root" / "calibration",
        [source],
        "Canada",
        11,
        plan,
    )
    assert events[3] == ("execute", ["calibrate"], "calibrator.log", 99)
    assert record["return_code"] == 0
    assert record["targets_available"] == 20
    assert record["pass_targets_available"] == 7
    assert record["target_limit"] == 7
    assert record["target_goal"] == 3
    assert record["summary"] == {"status": "completed", "visited": 7, "ok": 7}

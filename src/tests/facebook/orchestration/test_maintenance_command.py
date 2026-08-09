from __future__ import annotations

import json
from pathlib import Path

import pytest

from app.facebook.orchestration.adapters import FileStateStore
from app.facebook.orchestration.commands import (
    EvaluateCommandRequest,
    MaintenanceCommandHooks,
    SeedBaselineCommandRequest,
    run_evaluate_command,
    run_seed_baseline_command,
)
from app.facebook.runs import collect_run_metrics

pytestmark = pytest.mark.unit


def test_evaluate_command_returns_ten_for_two_zero_ad_windows(
    tmp_path: Path,
) -> None:
    previous_dir = _write_run(tmp_path / "previous", ads=0)
    current_dir = _write_run(tmp_path / "current", ads=0)
    previous_metrics = collect_run_metrics(
        previous_dir,
        expected_country="Canada",
        return_code=0,
    )
    state_path = tmp_path / "state.json"
    state_path.write_text(
        json.dumps(
            {
                "profiles": {
                    "profile": {
                        "runs": [
                            {
                                "at": "2026-08-09T10:00:00+00:00",
                                "run_dir": str(previous_dir),
                                "metrics": previous_metrics.to_dict(),
                            }
                        ]
                    }
                }
            }
        ),
        encoding="utf-8",
    )
    output: list[tuple[str, bool]] = []

    result = run_evaluate_command(
        EvaluateCommandRequest(
            state_path=state_path,
            run_dir=current_dir,
            profile_uuid="profile",
            expected_country="Canada",
            return_code=0,
            default_elapsed_seconds=None,
            default_scrolls=None,
            calibration_targets=5,
        ),
        _hooks(output),
    )

    payload = json.loads(output[0][0])
    assert result == 10
    assert output[0][1] is False
    assert payload["should_calibrate"] is True
    assert "zero_ads_repeated" in payload["reasons"]


def test_seed_baseline_command_rejects_incomplete_run(tmp_path: Path) -> None:
    run_dir = _write_run(tmp_path / "bad", ads=0)
    state_path = tmp_path / "state.json"
    output: list[tuple[str, bool]] = []

    result = run_seed_baseline_command(
        _seed_request(state_path, run_dir),
        _hooks(output),
    )

    assert result == 1
    assert output[0] == (
        "Run is not a good baseline candidate. "
        "Use a complete, geo-matched run with enough ads and targets.",
        True,
    )
    assert json.loads(output[1][0])["ads_total"] == 0
    assert output[1][1] is False
    assert not state_path.exists()


def test_seed_baseline_command_records_good_run(tmp_path: Path) -> None:
    run_dir = _write_run(tmp_path / "good", ads=10)
    state_path = tmp_path / "state.json"
    output: list[tuple[str, bool]] = []

    result = run_seed_baseline_command(
        _seed_request(state_path, run_dir),
        _hooks(output),
    )

    payload = json.loads(output[0][0])
    state = FileStateStore(state_path).load()
    assert result == 0
    assert output[0][1] is False
    assert payload["sample_count"] == 1
    assert state["profiles"]["profile"]["label"] == "Canada profile"
    assert state["profiles"]["profile"]["expected_country"] == "Canada"


def _write_run(path: Path, *, ads: int) -> Path:
    path.mkdir()
    (path / "run_meta.json").write_text(
        json.dumps(
            {
                "octo_profile_uuid": "profile",
                "profile_country": "Canada",
            }
        ),
        encoding="utf-8",
    )
    (path / "summary.json").write_text(
        json.dumps({"elapsed_seconds": 600, "scrolls": 80}),
        encoding="utf-8",
    )
    (path / "ads.json").write_text(
        json.dumps(
            [
                {
                    "fb_ad_id": str(index),
                    "landing_full": f"https://example{index}.test",
                }
                for index in range(ads)
            ]
        ),
        encoding="utf-8",
    )
    return path


def _seed_request(state_path: Path, run_dir: Path) -> SeedBaselineCommandRequest:
    return SeedBaselineCommandRequest(
        state_path=state_path,
        run_dir=run_dir,
        profile_uuid="profile",
        label="Canada profile",
        expected_country="Canada",
        default_elapsed_seconds=None,
        default_scrolls=None,
    )


def _hooks(output: list[tuple[str, bool]]) -> MaintenanceCommandHooks:
    return MaintenanceCommandHooks(
        state_store=FileStateStore,
        output=lambda message, flush: output.append((message, flush)),
    )

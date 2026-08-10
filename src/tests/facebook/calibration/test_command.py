from __future__ import annotations

import argparse
import json
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from app.facebook.calibration import CalibrationRunResult
from app.facebook.calibration.cli import runtime
from app.facebook.calibration.cli.parser import build_parser

pytestmark = pytest.mark.unit


def _saved_ad() -> dict[str, Any]:
    return {
        "relevant": True,
        "country": "Canada",
        "facebook_post_url": "https://www.facebook.com/100/posts/200",
        "advertiser": "Saved advertiser",
    }


def _args(ads_json: Path, run_dir: Path, *extra: str) -> argparse.Namespace:
    args: argparse.Namespace = build_parser().parse_args(
        [
            "--country",
            "Canada",
            "--ads-json",
            str(ads_json),
            "--run-dir",
            str(run_dir),
            *extra,
        ]
    )
    return args


def _prepare_runtime(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        runtime,
        "get_config",
        lambda: SimpleNamespace(
            facebook=SimpleNamespace(octo_profile_uuid="default-profile")
        ),
    )


def test_dry_run_writes_legacy_artifact_contract_without_connecting(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    _prepare_runtime(monkeypatch)
    ads_json = tmp_path / "ads.json"
    ads_json.write_text(json.dumps([_saved_ad()]), encoding="utf-8")
    run_dir = tmp_path / "calibration"
    monkeypatch.setattr(
        runtime,
        "acquire_command_session",
        lambda **_kwargs: (_ for _ in ()).throw(
            AssertionError("country-scoped dry run must not connect to Octo")
        ),
    )

    code = runtime.run_command(
        _args(ads_json, run_dir, "--dry-run"),
        stop_requested=lambda: False,
    )

    summary = json.loads((run_dir / "summary.json").read_text(encoding="utf-8"))
    targets = json.loads((run_dir / "targets.json").read_text(encoding="utf-8"))
    assert code == 0
    assert summary["status"] == "dry_run"
    assert (summary["targets"], summary["ok"], summary["failed"]) == (1, 0, 0)
    assert targets[0]["facebook_post_url"] == _saved_ad()["facebook_post_url"]


def test_no_saved_targets_keeps_legacy_status_and_exit_code(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    _prepare_runtime(monkeypatch)
    ads_json = tmp_path / "ads.json"
    ads_json.write_text(json.dumps([{**_saved_ad(), "relevant": False}]))
    run_dir = tmp_path / "calibration"

    code = runtime.run_command(
        _args(ads_json, run_dir, "--dry-run"),
        stop_requested=lambda: False,
    )

    summary = json.loads((run_dir / "summary.json").read_text(encoding="utf-8"))
    assert code == 1
    assert summary == {
        "status": "no_direct_facebook_targets",
        "finished_at": summary["finished_at"],
        "targets": 0,
        "ok": 0,
        "failed": 0,
    }


def test_runtime_maps_service_result_to_orchestrator_summary(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    _prepare_runtime(monkeypatch)
    ads_json = tmp_path / "ads.json"
    ads_json.write_text(json.dumps([_saved_ad()]), encoding="utf-8")
    run_dir = tmp_path / "calibration"
    monkeypatch.setattr(
        runtime,
        "_connect",
        lambda _args, _profile_uuid: ("ws://octo", {}, "Canada"),
    )

    def fake_session(
        *_args: Any,
        **kwargs: Any,
    ) -> tuple[CalibrationRunResult, dict[str, Any]]:
        item = {
            "ok": True,
            "view": {"status": "viewing"},
            "actions": [{"action": "reaction", "status": "clicked"}],
        }
        kwargs["artifacts"].record_result(item)
        return (
            CalibrationRunResult(
                results=(item,),
                interactions={
                    "successful": 1,
                    "already_active": 0,
                    "satisfied": 1,
                },
                target_goal_met=True,
                interaction_goal_met=True,
                infrastructure_error=None,
                termination="targets_exhausted",
            ),
            {"status": "closed"},
        )

    monkeypatch.setattr(runtime, "run_browser_session", fake_session)

    code = runtime.run_command(
        _args(ads_json, run_dir),
        stop_requested=lambda: False,
    )

    summary = json.loads((run_dir / "summary.json").read_text(encoding="utf-8"))
    assert code == 0
    assert summary["status"] == "completed"
    assert (summary["visited"], summary["ok"], summary["failed"]) == (1, 1, 0)
    assert summary["offer_funnel"] == {"status": "closed"}
    assert summary["results_path"] == str(run_dir / "results.json")

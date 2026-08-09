from __future__ import annotations

import json
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest

from app.facebook.calibration import CalibrationDecision, CalibrationPolicy
from app.facebook.orchestration.adapters import FileStateStore
from app.facebook.orchestration.lifecycle import (
    baseline_from_run_records,
    calibration_was_effective,
    is_healthy_relevance_result,
)
from app.facebook.profiles import Profile
from app.facebook.runs import RunMetrics
from app.services.facebook_orchestrator import (
    StateStore as LegacyStateStore,
)
from app.services.facebook_orchestrator import (
    _baseline_from_run_records as legacy_baseline_from_run_records,
)
from app.services.facebook_orchestrator import (
    _calibration_was_effective as legacy_calibration_was_effective,
)
from app.services.facebook_orchestrator import (
    _is_healthy_relevance_result as legacy_is_healthy_relevance_result,
)

pytestmark = pytest.mark.unit

NOW = "2026-08-09T12:00:00+00:00"


def decision() -> CalibrationDecision:
    return CalibrationDecision(
        status="healthy",
        should_calibrate=False,
        severity="none",
    )


def metrics(run_dir: str) -> RunMetrics:
    return RunMetrics(run_dir=run_dir, return_code=0)


def test_missing_and_malformed_state_fall_back_to_empty_profiles(
    tmp_path: Path,
) -> None:
    state_path = tmp_path / "state.json"
    store = FileStateStore(state_path)

    assert store.load() == {"profiles": {}}
    state_path.write_text("{not-json", encoding="utf-8")
    assert store.load() == {"profiles": {}}


def test_record_preserves_unknown_fields_and_retains_latest_100(tmp_path: Path) -> None:
    state_path = tmp_path / "state.json"
    old_runs = [
        {
            "at": f"old-{index}",
            "run_dir": f"old-{index}",
            "baseline_candidate": False,
            "metrics": metrics(f"old-{index}").to_dict(),
        }
        for index in range(105)
    ]
    old_calibrations = [{"at": f"calibration-{index}"} for index in range(105)]
    state_path.write_text(
        json.dumps(
            {
                "schema_extension": {"keep": True},
                "profiles": {
                    "profile": {
                        "octo_profile_uuid": "profile",
                        "custom_profile_field": "keep",
                        "runs": old_runs,
                        "calibrations": old_calibrations,
                    }
                },
            }
        ),
        encoding="utf-8",
    )
    store = FileStateStore(state_path, clock=lambda: NOW)

    store.record_profile_run(
        Profile(octo_profile_uuid="profile", label="Updated"),
        metrics("latest"),
        decision(),
        calibration={"at": "latest-calibration"},
        policy=CalibrationPolicy(),
    )

    state = store.load()
    profile_state = state["profiles"]["profile"]
    assert state["schema_extension"] == {"keep": True}
    assert profile_state["custom_profile_field"] == "keep"
    assert profile_state["label"] == "Updated"
    assert len(profile_state["runs"]) == 100
    assert profile_state["runs"][-1]["run_dir"] == "latest"
    assert len(profile_state["calibrations"]) == 100
    assert profile_state["calibrations"][-1]["at"] == "latest-calibration"
    assert profile_state["updated_at"] == NOW


def test_process_lock_prevents_lost_updates_between_store_instances(
    tmp_path: Path,
) -> None:
    state_path = tmp_path / "state.json"
    profile = Profile(octo_profile_uuid="profile")

    def record(index: int) -> None:
        FileStateStore(state_path, clock=lambda: NOW).record_profile_run(
            profile,
            metrics(f"run-{index}"),
            decision(),
            policy=CalibrationPolicy(),
        )

    with ThreadPoolExecutor(max_workers=8) as executor:
        tuple(executor.map(record, range(24)))

    history, _baseline, _calibrations = FileStateStore(state_path).profile_history(
        "profile"
    )
    assert {item.run_dir for item in history} == {f"run-{index}" for index in range(24)}


def test_effective_calibration_history_uses_timestamp_precedence(
    tmp_path: Path,
) -> None:
    state_path = tmp_path / "state.json"
    state_path.write_text(
        json.dumps(
            {
                "profiles": {
                    "profile": {
                        "runs": [],
                        "calibrations": [
                            {
                                "effective": True,
                                "at": "started",
                                "finished_at": "finished",
                            },
                            {"effective": False, "finished_at": "ignored"},
                        ],
                    }
                }
            }
        ),
        encoding="utf-8",
    )

    _history, _baseline, calibrations = FileStateStore(state_path).profile_history(
        "profile"
    )

    assert calibrations == ["finished"]


def test_seed_baseline_is_persisted_but_excluded_from_run_history(
    tmp_path: Path,
) -> None:
    store = FileStateStore(tmp_path / "state.json", clock=lambda: NOW)

    baseline = store.seed_baseline(
        "profile",
        metrics("seed"),
        label="Spain",
        expected_country="Spain",
        policy=CalibrationPolicy(),
    )
    history, persisted_baseline, _calibrations = store.profile_history("profile")

    assert baseline.sample_count == 1
    assert persisted_baseline.source_run_dirs == ["seed"]
    assert history == []
    assert store.profile_last_run_at("profile") is None


def test_state_queries_handle_legacy_fallbacks_and_invalid_offsets(
    tmp_path: Path,
) -> None:
    state_path = tmp_path / "state.json"
    fallback_metrics = metrics("fallback").to_dict()
    fallback_metrics["finished_at"] = "metric-finished"
    state_path.write_text(
        json.dumps(
            {
                "profiles": {
                    "profile": {
                        "runs": [
                            {"seed_baseline": True, "at": "seed"},
                            {"metrics": fallback_metrics},
                        ],
                        "calibrations": [
                            {"at": "attempt", "target_goal": []},
                        ],
                        "recovery_burst_count": "2",
                        "last_schedule": {
                            "kind": "recovery_burst",
                            "rest_seconds": 0,
                            "recovery_burst_count": 2,
                            "recovery_active": True,
                        },
                    }
                }
            }
        ),
        encoding="utf-8",
    )
    store = FileStateStore(state_path)

    assert store.profile_calibration_attempts("profile") == ["attempt"]
    assert store.profile_calibration_target_offset("profile") == 3
    assert store.profile_last_run_at("profile") == "metric-finished"
    assert store.profile_recovery_burst_count("profile") == 2
    assert store.profile_recovery_evaluation_active("profile") is True
    assert (
        store.profile_resume_schedule(
            "profile", default_rest_seconds=2700
        ).recovery_burst_count
        == 2
    )


def test_legacy_state_store_and_policy_names_remain_exact_aliases() -> None:
    assert LegacyStateStore is FileStateStore
    assert legacy_baseline_from_run_records is baseline_from_run_records
    assert legacy_calibration_was_effective is calibration_was_effective
    assert legacy_is_healthy_relevance_result is is_healthy_relevance_result

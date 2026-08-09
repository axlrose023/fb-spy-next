from __future__ import annotations

import json
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest

from app.facebook.calibration import CalibrationPolicy
from app.facebook.orchestration import CollectionPipelineState, RecoverySchedulePolicy
from app.facebook.orchestration.adapters import FileStateStore
from app.facebook.orchestration.commands import (
    ProfileCycleCommandHooks,
    ProfileCycleCommandRequest,
    run_profile_cycle_command,
)
from app.facebook.profiles import Profile

pytestmark = pytest.mark.unit

NOW = datetime(2026, 8, 9, 12, 30, 15, 123456, tzinfo=UTC)


def test_profile_cycle_command_adopts_geo_and_records_run(tmp_path: Path) -> None:
    events: list[str] = []
    logs: list[str] = []
    profile = Profile(octo_profile_uuid="profile-uuid", label="canada")
    state = FileStateStore(
        tmp_path / "state.json",
        clock=lambda: "2026-08-09T12:31:00+00:00",
    )

    @contextmanager
    def profile_lock(root_dir: Path, profile_uuid: str) -> Iterator[None]:
        events.append(f"lock-enter:{root_dir.name}:{profile_uuid}")
        try:
            yield
        finally:
            events.append("lock-exit")

    def run_collection(_profile: Profile, run_dir: Path) -> CollectionPipelineState:
        events.append("collect")
        (run_dir / "run_meta.json").write_text(
            json.dumps(
                {
                    "octo_profile_uuid": profile.octo_profile_uuid,
                    "profile_country": "Canada",
                }
            ),
            encoding="utf-8",
        )
        (run_dir / "summary.json").write_text(
            json.dumps({"elapsed_seconds": 600, "scrolls": 80}),
            encoding="utf-8",
        )
        (run_dir / "ads.json").write_text("[]", encoding="utf-8")
        return CollectionPipelineState()

    def write_json(path: Path, payload: Any) -> None:
        events.append("health")
        path.write_text(json.dumps(payload), encoding="utf-8")

    def count_calibration_targets(*_args: Any) -> int:
        events.append("count")
        return 4

    schedule = run_profile_cycle_command(
        _request(tmp_path, profile, state),
        ProfileCycleCommandHooks(
            profile_lock=profile_lock,
            run_collection=run_collection,
            persist_profile_country=lambda profile_uuid, country: events.append(
                f"persist:{profile_uuid}:{country}"
            ),
            update_calibration_pools=lambda *_args: events.append("pools"),
            count_calibration_targets=count_calibration_targets,
            run_calibration=lambda *_args: pytest.fail(
                "first observation must not calibrate"
            ),
            stop_profile=lambda _profile: events.append("stop"),
            write_json=write_json,
            stop_requested=lambda: True,
            now=lambda: NOW,
            log=logs.append,
        ),
    )

    run_dir = (
        tmp_path
        / "orchestrator"
        / "profiles"
        / profile.storage_name
        / "collect_20260809_123015_123456"
    )
    assert schedule.kind == "normal"
    assert profile.expected_country == "Canada"
    assert events == [
        "lock-enter:orchestrator:profile-uuid",
        "collect",
        "persist:profile-uuid:Canada",
        "pools",
        "count",
        "health",
        "stop",
        "lock-exit",
    ]
    assert logs[0] == f"[canada] collect -> {run_dir}"
    assert logs[1] == "[canada] adopted geo=Canada"
    assert (run_dir / "health.json").is_file()
    stored_metrics = state.load()["profiles"]["profile-uuid"]["runs"][0]["metrics"]
    assert stored_metrics["expected_country"] == "Canada"
    assert stored_metrics["calibration_targets_available"] == 4


@pytest.mark.parametrize(
    ("dry_run", "expected_events"),
    [
        (False, ["lock-enter", "collect", "stop", "lock-exit"]),
        (True, ["lock-enter", "collect", "lock-exit"]),
    ],
)
def test_profile_cycle_command_releases_lock_after_collection_error(
    tmp_path: Path,
    dry_run: bool,
    expected_events: list[str],
) -> None:
    events: list[str] = []
    profile = Profile(octo_profile_uuid="profile-uuid")

    @contextmanager
    def profile_lock(_root_dir: Path, _profile_uuid: str) -> Iterator[None]:
        events.append("lock-enter")
        try:
            yield
        finally:
            events.append("lock-exit")

    def fail_collection(
        _profile: Profile,
        _run_dir: Path,
    ) -> CollectionPipelineState:
        events.append("collect")
        raise RuntimeError("collector failed")

    request = _request(
        tmp_path,
        profile,
        FileStateStore(tmp_path / "state.json"),
        dry_run=dry_run,
    )
    hooks = ProfileCycleCommandHooks(
        profile_lock=profile_lock,
        run_collection=fail_collection,
        persist_profile_country=lambda *_args: None,
        update_calibration_pools=lambda *_args: None,
        count_calibration_targets=lambda *_args: 0,
        run_calibration=lambda *_args: {},
        stop_profile=lambda _profile: events.append("stop"),
        write_json=lambda *_args: None,
        stop_requested=lambda: False,
        now=lambda: NOW,
        log=lambda _message: None,
    )

    with pytest.raises(RuntimeError, match="collector failed"):
        run_profile_cycle_command(request, hooks)

    assert events == expected_events


def _request(
    tmp_path: Path,
    profile: Profile,
    state: FileStateStore,
    *,
    dry_run: bool = False,
) -> ProfileCycleCommandRequest:
    return ProfileCycleCommandRequest(
        profile=profile,
        state=state,
        policy=CalibrationPolicy(),
        schedule_policy=RecoverySchedulePolicy(900, 3, 0, 300),
        root_dir=tmp_path / "orchestrator",
        collect_seconds=600,
        recovery_burst_cycles=3,
        dry_run=dry_run,
    )

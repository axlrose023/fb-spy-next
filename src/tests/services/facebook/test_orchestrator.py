import json
import sys
import threading
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import pytest

from app.facebook.calibration import (
    CalibrationDecision,
    CalibrationPlan,
    CalibrationPolicy,
)
from app.facebook.orchestration import (
    ProfileCycleSchedule,
    RecoverySchedulePolicy,
    calibration_pass_target_cap,
    calibration_passes_for_cycle,
    next_profile_schedule,
    recovery_evaluation_policy,
    remaining_daily_calibration_attempts,
    remaining_profile_rest_seconds,
)
from app.facebook.orchestration.adapters import FileLock, FileStateStore
from app.facebook.orchestration.commands import (
    build_parser,
    calibration_policy_from_args,
    profile_rest_seconds_from_args,
    schedule_policy_from_args,
)
from app.facebook.orchestration.lifecycle import (
    baseline_from_run_records,
    calibration_was_effective,
)
from app.facebook.orchestration.runtime import DEFAULT_CONTEXT
from app.facebook.orchestration.runtime import application as runtime_application
from app.facebook.orchestration.runtime import calibration as runtime_calibration
from app.facebook.orchestration.runtime import collection as runtime_collection
from app.facebook.orchestration.runtime import cycle as runtime_cycle
from app.facebook.orchestration.runtime import profiles as runtime_profiles
from app.facebook.profiles import Profile
from app.facebook.runs import RunMetrics

ProfileConfig = Profile
StateStore = FileStateStore
_baseline_from_run_records = baseline_from_run_records
_build_parser = build_parser
_calibration_ads_paths = runtime_calibration.calibration_ads_paths
_calibration_pass_target_cap = calibration_pass_target_cap
_calibration_passes_for_cycle = calibration_passes_for_cycle
_calibration_policy = calibration_policy_from_args
_calibration_was_effective = calibration_was_effective
_count_calibration_targets = runtime_calibration.count_calibration_targets
_effective_calibration_target_goal = (
    runtime_calibration.effective_calibration_target_goal
)
_load_profiles = runtime_profiles.load_profiles
_merge_public_profiles = runtime_profiles.merge_public_profiles
_next_profile_schedule = next_profile_schedule
_persist_profile_country = runtime_profiles.persist_profile_country
_profile_evaluation_policy = recovery_evaluation_policy
_profile_rest_seconds = profile_rest_seconds_from_args
_profile_schedule_policy = schedule_policy_from_args
_remaining_daily_calibration_attempts = remaining_daily_calibration_attempts
_remaining_profile_rest_seconds = remaining_profile_rest_seconds
_update_calibration_pools = runtime_calibration.update_calibration_pools


def _backend_import_command(profile: Profile, ads_json_path) -> list[str]:
    return runtime_collection.backend_import_command(
        profile,
        ads_json_path,
        DEFAULT_CONTEXT,
    )


def _calibration_plan(
    decision: CalibrationDecision,
    args,
    available_targets: int,
) -> CalibrationPlan:
    return runtime_calibration.calibration_plan(decision, args, available_targets)


def _calibration_timeout_seconds(args, *, target_limit=None) -> float:
    return runtime_calibration.timeout_seconds(args, target_limit=target_limit)


def _calibrator_command(profile, args, run_dir, ads_paths, country, **kwargs):
    return runtime_calibration.calibrator_command(
        profile,
        args,
        run_dir,
        ads_paths,
        country,
        DEFAULT_CONTEXT,
        **kwargs,
    )


def _discover_profiles(args, *, fail_fast: bool) -> None:
    runtime_profiles.discover_profiles(args, DEFAULT_CONTEXT, fail_fast=fail_fast)


def _run(args) -> int:
    return runtime_application.run(args, DEFAULT_CONTEXT)


def _run_calibration(profile, args, collect_dir, root_dir, **kwargs):
    return runtime_calibration.run_calibration(
        profile,
        args,
        collect_dir,
        root_dir,
        DEFAULT_CONTEXT,
        **kwargs,
    )


def _run_command(command, log_path, **kwargs) -> int:
    return DEFAULT_CONTEXT.run_command(command, log_path, **kwargs)


def _run_profile_cycle(profile, args, store, policy, root_dir):
    return runtime_cycle.run_profile_cycle(
        profile,
        args,
        store,
        policy,
        root_dir,
        DEFAULT_CONTEXT,
    )


def test_profile_file_lock_releases_immediately(tmp_path) -> None:
    lock_path = tmp_path / "profile.lock"
    with FileLock(lock_path):
        with pytest.raises(RuntimeError, match="profile locked"):
            with FileLock(lock_path):
                pass

    with FileLock(lock_path):
        assert lock_path.exists()


def test_calibration_target_offset_uses_actual_visited_targets(tmp_path) -> None:
    state_path = tmp_path / "state.json"
    state_path.write_text(
        json.dumps(
            {
                "profiles": {
                    "profile": {
                        "calibrations": [
                            {"summary": {"visited": 8}},
                            {"target_limit": 30},
                            {"target_goal": 10},
                        ]
                    }
                }
            }
        ),
        encoding="utf-8",
    )

    assert StateStore(state_path).profile_calibration_target_offset("profile") == 48


def test_quality_guard_bootstraps_first_healthy_run_as_trusted(tmp_path) -> None:
    store = StateStore(tmp_path / "state.json")
    profile = ProfileConfig(octo_profile_uuid="dominican", quality_guard=True)
    policy = CalibrationPolicy()
    metrics = RunMetrics(
        run_dir="healthy",
        profile_uuid="dominican",
        profile_country="Dominican Republic",
        expected_country="Dominican Republic",
        return_code=0,
        stop_reason="time_budget",
        elapsed_seconds=900,
        scrolls=300,
        ads_total=25,
        target_ads=20,
        target_source="relevance",
        geo_observed=True,
        geo_match=True,
        relevance_known=True,
        relevance_classified_ads=25,
        relevance_coverage=1.0,
        relevant_ads=20,
        relevant_rate=0.8,
        ads_per_hour=100,
        target_per_hour=80,
        ads_per_100_scrolls=25 / 3,
        target_per_100_scrolls=20 / 3,
    )
    decision = CalibrationDecision(
        status="watch",
        should_calibrate=False,
        severity="low",
    )

    store.record_profile_run(profile, metrics, decision, policy=policy)
    _history, baseline, _calibrations = store.profile_history("dominican")

    assert baseline.trusted is True
    assert baseline.relevant_rate == 0.8


def test_failed_recovery_escalates_to_configured_calibration_passes() -> None:
    profile = ProfileConfig(
        octo_profile_uuid="dominican",
        failed_recovery_calibration_passes=2,
    )
    previous = RunMetrics(
        run_dir="previous",
        target_source="relevance",
        relevance_known=True,
        relevance_classified_ads=25,
        relevant_ads=5,
        relevant_rate=0.2,
        target_per_hour=20,
    )
    current = RunMetrics(
        run_dir="current",
        target_source="relevance",
        relevance_known=True,
        relevance_classified_ads=25,
        relevant_ads=4,
        relevant_rate=0.16,
        target_per_hour=16,
    )

    assert (
        _calibration_passes_for_cycle(
            profile,
            current,
            [previous],
            recovery_active=True,
        )
        == 2
    )
    assert (
        _calibration_passes_for_cycle(
            profile,
            current,
            [previous],
            recovery_active=False,
        )
        == 1
    )


def test_multiple_calibration_passes_are_counted_and_rotated(tmp_path) -> None:
    store = StateStore(tmp_path / "state.json")
    profile = ProfileConfig(octo_profile_uuid="dominican")
    metrics = RunMetrics(run_dir="bad", return_code=0)
    decision = CalibrationDecision(
        status="calibrate",
        should_calibrate=True,
        severity="medium",
        reasons=["proactive_quality_drop"],
    )

    store.record_profile_run(
        profile,
        metrics,
        decision,
        calibrations=[
            {
                "at": "2026-07-21T10:00:00+00:00",
                "summary": {"status": "completed", "visited": 30},
            },
            {
                "at": "2026-07-21T10:30:00+00:00",
                "summary": {"status": "completed", "visited": 20},
            },
        ],
        policy=CalibrationPolicy(),
    )

    assert store.profile_calibration_target_offset("dominican") == 50
    assert len(store.profile_calibration_attempts("dominican")) == 2


def test_double_pass_respects_remaining_daily_attempt_budget() -> None:
    now = datetime(2026, 7, 21, 12, tzinfo=UTC)
    recent = [
        (now.replace(minute=0) - timedelta(minutes=index)).isoformat()
        for index in range(35)
    ]

    assert _remaining_daily_calibration_attempts(recent, limit=36, now=now) == 1


@pytest.mark.parametrize(
    ("remaining", "passes", "expected"),
    [(100, 2, 50), (60, 2, 30), (30, 2, 15), (8, 2, 4), (5, 2, 5)],
)
def test_double_pass_splits_pool_without_reusing_targets(
    remaining,
    passes,
    expected,
) -> None:
    assert (
        _calibration_pass_target_cap(
            remaining,
            passes_left=passes,
            min_targets=3,
        )
        == expected
    )


def test_run_command_times_out_and_marks_log(tmp_path) -> None:
    log_path = tmp_path / "runner.log"

    code = _run_command(
        [sys.executable, "-c", "import time; time.sleep(30)"],
        log_path,
        timeout_seconds=0.2,
        interrupt_grace_seconds=0.2,
    )

    assert code == 124
    assert "command timeout" in log_path.read_text(encoding="utf-8")


def test_loop_reschedules_profile_without_waiting_for_other_profile(
    tmp_path,
    monkeypatch,
) -> None:
    profiles_path = tmp_path / "profiles.json"
    profiles_path.write_text(
        json.dumps(
            {
                "profiles": [
                    {"octo_profile_uuid": "fast-profile", "label": "fast"},
                    {"octo_profile_uuid": "slow-profile", "label": "slow"},
                ]
            }
        ),
        encoding="utf-8",
    )
    fast_second_cycle = threading.Event()
    slow_finished = threading.Event()
    fast_runs = 0

    def fake_cycle(profile, *_args):
        nonlocal fast_runs
        if profile.octo_profile_uuid == "fast-profile":
            fast_runs += 1
            if fast_runs == 2:
                assert not slow_finished.is_set()
                fast_second_cycle.set()
            return
        assert fast_second_cycle.wait(timeout=5)
        slow_finished.set()

    monkeypatch.setattr(
        "app.facebook.orchestration.runtime.cycle.run_profile_cycle",
        fake_cycle,
    )
    args = _build_parser().parse_args(
        [
            "run",
            "--profiles-json",
            str(profiles_path),
            "--state-json",
            str(tmp_path / "state.json"),
            "--root-dir",
            str(tmp_path / "root"),
            "--max-parallel",
            "2",
            "--cycle-sleep",
            "0",
            "--max-cycles",
            "3",
            "--loop",
        ]
    )

    assert _run(args) == 0
    assert fast_second_cycle.is_set()
    assert slow_finished.is_set()


def test_loop_queues_profiles_beyond_parallel_limit_without_losing_them(
    tmp_path,
    monkeypatch,
) -> None:
    profile_ids = [f"profile-{index}" for index in range(7)]
    profiles_path = tmp_path / "profiles.json"
    profiles_path.write_text(
        json.dumps(
            {
                "profiles": [
                    {"octo_profile_uuid": profile_id, "label": profile_id}
                    for profile_id in profile_ids
                ]
            }
        ),
        encoding="utf-8",
    )
    first_wave_barrier = threading.Barrier(5)
    lock = threading.Lock()
    started: list[str] = []
    first_wave: list[str] = []
    active = 0
    max_active = 0

    def fake_cycle(profile, *_args):
        nonlocal active, max_active
        with lock:
            active += 1
            max_active = max(max_active, active)
            started.append(profile.octo_profile_uuid)
            if len(started) <= 5:
                first_wave.append(profile.octo_profile_uuid)
        if profile.octo_profile_uuid in profile_ids[:5]:
            first_wave_barrier.wait(timeout=5)
        with lock:
            active -= 1
        return ProfileCycleSchedule(kind="normal", rest_seconds=0)

    monkeypatch.setattr(
        "app.facebook.orchestration.runtime.cycle.run_profile_cycle",
        fake_cycle,
    )
    args = _build_parser().parse_args(
        [
            "run",
            "--profiles-json",
            str(profiles_path),
            "--state-json",
            str(tmp_path / "state.json"),
            "--root-dir",
            str(tmp_path / "root"),
            "--max-parallel",
            "5",
            "--cycle-sleep",
            "0",
            "--max-cycles",
            "7",
            "--loop",
        ]
    )

    assert _run(args) == 0
    assert set(first_wave) == set(profile_ids[:5])
    assert set(profile_ids).issubset(started)
    assert max_active == 5


def test_immediate_recovery_does_not_starve_older_due_profile(
    tmp_path,
    monkeypatch,
) -> None:
    profiles_path = tmp_path / "profiles.json"
    profiles_path.write_text(
        json.dumps(
            {
                "profiles": [
                    {"octo_profile_uuid": "recovering", "label": "recovering"},
                    {"octo_profile_uuid": "waiting", "label": "waiting"},
                ]
            }
        ),
        encoding="utf-8",
    )
    order: list[str] = []

    def fake_cycle(profile, *_args):
        order.append(profile.octo_profile_uuid)
        if profile.octo_profile_uuid == "recovering":
            return ProfileCycleSchedule(
                kind="recovery_burst",
                rest_seconds=0,
                recovery_burst_count=1,
                recovery_attempt=1,
                recovery_active=True,
            )
        return ProfileCycleSchedule(kind="normal", rest_seconds=0)

    monkeypatch.setattr(
        "app.facebook.orchestration.runtime.cycle.run_profile_cycle",
        fake_cycle,
    )
    args = _build_parser().parse_args(
        [
            "run",
            "--profiles-json",
            str(profiles_path),
            "--state-json",
            str(tmp_path / "state.json"),
            "--root-dir",
            str(tmp_path / "root"),
            "--max-parallel",
            "1",
            "--cycle-sleep",
            "0",
            "--max-cycles",
            "2",
            "--loop",
        ]
    )

    assert _run(args) == 0
    assert order == ["recovering", "waiting"]


def test_profile_rest_uses_larger_explicit_delay() -> None:
    parser = _build_parser()
    args = parser.parse_args(
        [
            "run",
            "--cycle-sleep",
            "60",
            "--profile-rest-minutes",
            "15",
        ]
    )

    assert _profile_rest_seconds(args) == 900


def test_recovery_schedule_runs_three_calibrations_before_normal_rest() -> None:
    schedule_policy = RecoverySchedulePolicy(
        normal_rest_seconds=45 * 60,
        burst_limit=3,
        burst_rest_seconds=0,
        infrastructure_retry_seconds=5 * 60,
    )
    metrics = RunMetrics(run_dir="bad", return_code=0)
    decision = CalibrationDecision(
        status="calibrate",
        should_calibrate=True,
        severity="high",
        reasons=["zero_relevant_ads"],
    )
    calibration = {"summary": {"status": "completed", "ok": 10}}

    first = _next_profile_schedule(
        previous_burst_count=0,
        metrics=metrics,
        decision=decision,
        calibration=calibration,
        policy=schedule_policy,
    )
    second = _next_profile_schedule(
        previous_burst_count=first.recovery_burst_count,
        metrics=metrics,
        decision=decision,
        calibration=calibration,
        policy=schedule_policy,
    )
    third = _next_profile_schedule(
        previous_burst_count=second.recovery_burst_count,
        metrics=metrics,
        decision=decision,
        calibration=calibration,
        policy=schedule_policy,
    )

    assert first == ProfileCycleSchedule(
        kind="recovery_burst",
        rest_seconds=0,
        recovery_burst_count=1,
        recovery_attempt=1,
        recovery_active=True,
    )
    assert second.recovery_attempt == 2
    assert second.rest_seconds == 0
    assert third == ProfileCycleSchedule(
        kind="recovery_burst_rest",
        rest_seconds=45 * 60,
        recovery_burst_count=0,
        recovery_attempt=3,
        recovery_active=True,
    )


def test_healthy_validation_resets_recovery_burst() -> None:
    schedule = _next_profile_schedule(
        previous_burst_count=2,
        metrics=RunMetrics(run_dir="healthy", return_code=0),
        decision=CalibrationDecision(
            status="healthy",
            should_calibrate=False,
            severity="none",
        ),
        calibration=None,
        policy=RecoverySchedulePolicy(2700, 3, 0, 300),
    )

    assert schedule.kind == "normal"
    assert schedule.rest_seconds == 2700
    assert schedule.recovery_burst_count == 0


def test_infrastructure_failure_does_not_consume_recovery_attempt() -> None:
    schedule = _next_profile_schedule(
        previous_burst_count=1,
        metrics=RunMetrics(
            run_dir="proxy-error",
            return_code=2,
            stop_reason="octo_proxy_error",
        ),
        decision=CalibrationDecision(
            status="manual_review",
            should_calibrate=False,
            severity="blocked",
        ),
        calibration=None,
        policy=RecoverySchedulePolicy(2700, 3, 0, 300),
    )

    assert schedule.kind == "infrastructure_retry"
    assert schedule.rest_seconds == 300
    assert schedule.recovery_burst_count == 1


def test_blocked_resolve_timeout_uses_short_retry_without_calibration() -> None:
    schedule = _next_profile_schedule(
        previous_burst_count=0,
        metrics=RunMetrics(
            run_dir="resolve-timeout",
            return_code=0,
            stop_reason="resolve_timeout",
        ),
        decision=CalibrationDecision(
            status="watch",
            should_calibrate=False,
            severity="blocked",
            reasons=["zero_relevant_ads"],
            blockers=[
                "collector_stop_reason_resolve_timeout",
                "insufficient_elapsed_time",
            ],
        ),
        calibration=None,
        policy=RecoverySchedulePolicy(2700, 3, 0, 300),
    )

    assert schedule.kind == "infrastructure_retry"
    assert schedule.rest_seconds == 300
    assert schedule.recovery_burst_count == 0


def test_actionable_resolve_timeout_still_enters_recovery_burst() -> None:
    schedule = _next_profile_schedule(
        previous_burst_count=0,
        metrics=RunMetrics(
            run_dir="actionable-timeout",
            return_code=0,
            stop_reason="resolve_timeout",
        ),
        decision=CalibrationDecision(
            status="calibrate",
            should_calibrate=True,
            severity="high",
            reasons=["zero_relevant_ads"],
        ),
        calibration={"summary": {"status": "completed", "ok": 20}},
        policy=RecoverySchedulePolicy(2700, 3, 0, 300),
    )

    assert schedule.kind == "recovery_burst"
    assert schedule.recovery_attempt == 1


def test_relevance_classifier_error_uses_short_retry() -> None:
    schedule = _next_profile_schedule(
        previous_burst_count=0,
        metrics=RunMetrics(run_dir="classifier-error", return_code=0),
        decision=CalibrationDecision(
            status="healthy",
            should_calibrate=False,
            severity="none",
        ),
        calibration=None,
        policy=RecoverySchedulePolicy(2700, 3, 0, 300),
        infrastructure_retry_required=True,
    )

    assert schedule.kind == "infrastructure_retry"
    assert schedule.rest_seconds == 300


def test_active_recovery_burst_bypasses_only_calibration_cooldowns() -> None:
    policy = CalibrationPolicy(
        calibration_cooldown_seconds=3600,
        zero_ads_calibration_cooldown_seconds=1800,
        calibration_retry_cooldown_seconds=1800,
        max_calibrations_per_24h=36,
    )

    active = _profile_evaluation_policy(policy, recovery_active=True)
    inactive = _profile_evaluation_policy(policy, recovery_active=False)
    guarded = _profile_evaluation_policy(
        policy,
        recovery_active=False,
        quality_guard=True,
    )

    assert active.calibration_cooldown_seconds == 0
    assert active.zero_ads_calibration_cooldown_seconds == 0
    assert active.calibration_retry_cooldown_seconds == 0
    assert active.max_calibrations_per_24h == 36
    assert active.zero_ads_calibration_burst_limit == 37
    assert inactive.calibration_cooldown_seconds == 3600
    assert guarded.proactive_quality_drop_enabled is True


def test_recovery_schedule_is_persisted_for_restart(tmp_path) -> None:
    store = StateStore(tmp_path / "state.json")
    profile = ProfileConfig(octo_profile_uuid="profile", label="Spain")
    args = _build_parser().parse_args(
        ["run", "--profile-rest-minutes", "45", "--cycle-sleep", "0"]
    )
    schedule = store.record_profile_run(
        profile,
        RunMetrics(run_dir="bad", return_code=0),
        CalibrationDecision(
            status="calibrate",
            should_calibrate=True,
            severity="high",
            reasons=["zero_relevant_ads"],
        ),
        calibration={"summary": {"status": "completed", "ok": 10}},
        policy=CalibrationPolicy(),
        schedule_policy=_profile_schedule_policy(args),
    )

    resumed = StateStore(tmp_path / "state.json").profile_resume_schedule(
        profile.octo_profile_uuid,
        default_rest_seconds=2700,
    )

    assert schedule == resumed
    assert resumed.recovery_burst_count == 1
    assert resumed.rest_seconds == 0


def test_completed_burst_remains_recovery_active_after_backoff(tmp_path) -> None:
    store = StateStore(tmp_path / "state.json")
    profile = ProfileConfig(octo_profile_uuid="profile", label="Spain")
    schedule_policy = RecoverySchedulePolicy(2700, 3, 0, 300)
    metrics = RunMetrics(run_dir="bad", return_code=0)
    decision = CalibrationDecision(
        status="calibrate",
        should_calibrate=True,
        severity="high",
        reasons=["zero_relevant_ads"],
    )
    calibration = {"summary": {"status": "completed", "ok": 10}}

    for _ in range(3):
        schedule = store.record_profile_run(
            profile,
            metrics,
            decision,
            calibration=calibration,
            policy=CalibrationPolicy(),
            schedule_policy=schedule_policy,
        )

    assert schedule.kind == "recovery_burst_rest"
    assert schedule.recovery_burst_count == 0
    assert store.profile_recovery_evaluation_active(profile.octo_profile_uuid)

    retry = _next_profile_schedule(
        previous_burst_count=0,
        previous_recovery_active=True,
        metrics=RunMetrics(
            run_dir="proxy-error",
            return_code=2,
            stop_reason="octo_proxy_error",
        ),
        decision=CalibrationDecision(
            status="manual_review",
            should_calibrate=False,
            severity="blocked",
        ),
        calibration=None,
        policy=schedule_policy,
    )
    assert retry.kind == "infrastructure_retry"
    assert retry.recovery_active


def test_maintenance_calibration_does_not_start_recovery_burst() -> None:
    schedule = _next_profile_schedule(
        previous_burst_count=0,
        metrics=RunMetrics(run_dir="maintenance", return_code=0),
        decision=CalibrationDecision(
            status="calibrate",
            should_calibrate=True,
            severity="low",
            reasons=["periodic_account_maintenance"],
        ),
        calibration={"summary": {"status": "completed", "ok": 10}},
        policy=RecoverySchedulePolicy(2700, 3, 0, 300),
    )

    assert schedule.kind == "normal"
    assert schedule.rest_seconds == 2700
    assert schedule.recovery_burst_count == 0


def test_run_calibration_policy_uses_tunable_safety_limits() -> None:
    args = _build_parser().parse_args(
        [
            "run",
            "--calibration-cooldown-hours",
            "1",
            "--soft-drop-calibration-windows",
            "3",
            "--watch-drop-ratio",
            "0.95",
            "--immediate-drop-ratio",
            "0.70",
            "--minimum-healthy-relevant-rate",
            "0.75",
            "--minimum-healthy-relevant-ads",
            "15",
            "--zero-ads-windows",
            "1",
            "--absolute-low-ads-windows",
            "2",
            "--absolute-low-ads-per-hour",
            "12",
            "--zero-ads-calibration-cooldown-minutes",
            "30",
            "--zero-ads-calibration-burst-limit",
            "8",
            "--zero-ads-calibration-backoff-hours",
            "2",
            "--calibration-retry-cooldown-hours",
            "0.5",
            "--maintenance-calibration-hours",
            "6",
            "--maintenance-min-valid-windows",
            "3",
            "--max-calibrations-per-24h",
            "24",
        ]
    )

    policy = _calibration_policy(args)

    assert policy.zero_ads_windows == 1
    assert policy.absolute_low_ads_windows == 2
    assert policy.absolute_low_ads_per_hour == 12
    assert policy.soft_drop_calibration_windows == 3
    assert policy.watch_drop_ratio == 0.95
    assert policy.immediate_drop_ratio == 0.70
    assert policy.minimum_healthy_relevant_rate == 0.75
    assert policy.minimum_healthy_relevant_ads == 15
    assert policy.calibration_cooldown_seconds == 1 * 60 * 60
    assert policy.zero_ads_calibration_cooldown_seconds == 30 * 60
    assert policy.zero_ads_calibration_burst_limit == 8
    assert policy.zero_ads_calibration_backoff_seconds == 2 * 60 * 60
    assert policy.calibration_retry_cooldown_seconds == 30 * 60
    assert policy.maintenance_calibration_interval_seconds == 6 * 60 * 60
    assert policy.maintenance_min_valid_windows == 3
    assert policy.max_calibrations_per_24h == 24


def test_profile_rest_survives_orchestrator_restart() -> None:
    now = datetime(2026, 7, 15, 18, 0, tzinfo=UTC)

    assert (
        _remaining_profile_rest_seconds(
            "2026-07-15T17:55:00+00:00",
            15 * 60,
            now=now,
        )
        == 10 * 60
    )
    assert (
        _remaining_profile_rest_seconds(
            "2026-07-15T17:30:00+00:00",
            15 * 60,
            now=now,
        )
        == 0
    )


def test_backend_import_command_uses_already_classified_file(
    tmp_path,
) -> None:
    path = tmp_path / "ads.relevant.json"
    profile = ProfileConfig(octo_profile_uuid="profile", label="spain")

    command = _backend_import_command(profile, path)

    assert "app.facebook.runs.commands" in command
    assert command[command.index("--ads-json") + 1] == str(path)
    assert command[command.index("--title") + 1].startswith("spain - ")


def test_profile_cycle_imports_classified_run_into_backend(
    tmp_path,
    monkeypatch,
) -> None:
    profile = ProfileConfig(
        octo_profile_uuid="profile",
        label="spain",
        expected_country="Spain",
    )
    command_order: list[str] = []

    def fake_command(_context, command, log_path, **_kwargs):
        run_dir = log_path.parent
        if log_path.name == "runner.log":
            command_order.append("collect")
            (run_dir / "run_meta.json").write_text(
                json.dumps(
                    {
                        "octo_profile_uuid": profile.octo_profile_uuid,
                        "profile_country": "Spain",
                    }
                ),
                encoding="utf-8",
            )
            (run_dir / "summary.json").write_text(
                json.dumps(
                    {
                        "elapsed_seconds": 60,
                        "scrolls": 10,
                        "interest_safe_mode": True,
                        "resolve_enabled": False,
                        "active_actions": {
                            "cta_click_attempts": 0,
                            "video_play_attempts": 0,
                            "comment_open_attempts": 0,
                        },
                        "passive_media_guard": {
                            "installed": True,
                            "init_script_installed": True,
                            "media_route_installed": True,
                        },
                    }
                ),
                encoding="utf-8",
            )
            (run_dir / "ads.json").write_text("[]", encoding="utf-8")
        elif log_path.name == "relevance.log":
            command_order.append("classify")
            (run_dir / "ads.relevant.json").write_text("[]", encoding="utf-8")
        elif log_path.name == "backend_import.log":
            command_order.append("import")
            assert command[command.index("--ads-json") + 1].endswith(
                "ads.relevant.json"
            )
        return 0

    monkeypatch.setattr(
        "app.facebook.orchestration.runtime.context.RuntimeContext.run_command",
        fake_command,
    )
    monkeypatch.setattr(
        "app.facebook.orchestration.runtime.profiles.stop_octo_profile",
        lambda *_args: command_order.append("stop"),
    )
    args = _build_parser().parse_args(
        [
            "run",
            "--profiles-json",
            str(tmp_path / "profiles.json"),
            "--state-json",
            str(tmp_path / "state.json"),
            "--root-dir",
            str(tmp_path / "root"),
            "--collect-minutes",
            "1",
            "--classify-relevance",
            "--import-backend",
        ]
    )

    _run_profile_cycle(
        profile,
        args,
        StateStore(tmp_path / "state.json"),
        CalibrationPolicy(),
        tmp_path / "root",
    )

    assert command_order == ["collect", "classify", "import", "stop"]


def test_missing_public_api_token_does_not_block_configured_profiles(
    tmp_path,
    monkeypatch,
) -> None:
    profiles_path = tmp_path / "profiles.json"
    profiles_path.write_text(
        '{"profiles":[{"octo_profile_uuid":"known-profile"}]}',
        encoding="utf-8",
    )
    monkeypatch.delenv("OCTO_API_TOKEN", raising=False)
    monkeypatch.setattr(
        DEFAULT_CONTEXT,
        "config_provider",
        lambda: SimpleNamespace(
            facebook=SimpleNamespace(octo_api_token="", octo_search_tags=""),
        ),
    )
    monkeypatch.setattr(
        "app.facebook.orchestration.runtime.profiles.merge_public_profiles",
        lambda *_args, **_kwargs: pytest.fail("public discovery must be skipped"),
    )
    args = _build_parser().parse_args(
        [
            "run",
            "--profiles-json",
            str(profiles_path),
            "--discover-octo-profiles",
        ]
    )

    _discover_profiles(args, fail_fast=True)

    assert [profile.octo_profile_uuid for profile in _load_profiles(profiles_path)] == [
        "known-profile"
    ]


def test_failed_calibration_does_not_count_for_cooldown() -> None:
    assert not _calibration_was_effective(
        {
            "return_code": 2,
            "summary": {"status": "failed", "ok": 0},
        }
    )
    assert _calibration_was_effective(
        {
            "return_code": 2,
            "summary": {"status": "completed", "ok": 8, "failed": 2},
            "effective": True,
        }
    )
    assert not _calibration_was_effective(
        {
            "return_code": 0,
            "summary": {
                "status": "completed",
                "ok": 2,
                "interaction_goal_met": True,
            },
        }
    )
    assert not _calibration_was_effective(
        {
            "return_code": 0,
            "summary": {
                "status": "completed",
                "ok": 3,
                "interaction_goal_met": False,
            },
        }
    )
    assert _calibration_was_effective(
        {
            "return_code": 0,
            "summary": {
                "status": "completed",
                "ok": 3,
                "interaction_goal_met": True,
            },
        }
    )


def test_calibrator_command_uses_success_threshold_not_pool_threshold(tmp_path) -> None:
    args = _build_parser().parse_args(["run"])
    command = _calibrator_command(
        ProfileConfig(octo_profile_uuid="spain-profile", expected_country="Spain"),
        args,
        tmp_path / "calibration",
        [tmp_path / "ads.relevant.json"],
        "Spain",
        min_successful_targets=8,
    )

    value_index = command.index("--min-successful-targets") + 1
    assert command[value_index] == "8"
    offset_index = command.index("--target-offset") + 1
    assert command[offset_index] == "0"
    health_index = command.index("--target-health-json") + 1
    assert command[health_index] == str(tmp_path / "calibration_target_health.json")
    assert CalibrationPolicy().min_calibration_targets == 3
    assert CalibrationPolicy().min_successful_calibration_targets == 3


@pytest.mark.parametrize(
    ("reasons", "available", "tier", "limit", "goal", "budgets"),
    [
        (["periodic_account_maintenance"], 100, "standard", 20, 10, (6, 2, 0, 1)),
        (
            ["relevance_rate_below_minimum"],
            100,
            "low_relevance",
            30,
            30,
            (9, 3, 0, 3),
        ),
        (["too_few_relevant_ads"], 14, "low_relevance", 14, 14, (6, 2, 0, 2)),
        (
            ["zero_relevant_ads"],
            100,
            "recovery",
            50,
            40,
            (15, 5, 0, 5),
        ),
        (["zero_ads_repeated"], 12, "recovery", 12, 12, (6, 2, 0, 2)),
    ],
)
def test_calibration_plan_scales_with_health_severity(
    reasons,
    available,
    tier,
    limit,
    goal,
    budgets,
) -> None:
    args = _build_parser().parse_args(["run"])
    args.calibration_offer_funnel = False
    decision = CalibrationDecision(
        status="calibrate",
        should_calibrate=True,
        severity="medium",
        reasons=reasons,
    )

    plan = _calibration_plan(decision, args, available)

    assert plan.tier == tier
    assert plan.target_limit == limit
    assert plan.target_goal == goal
    assert (
        plan.max_reactions,
        plan.max_follows,
        plan.max_comments,
        plan.min_interactions,
    ) == budgets


def test_funnel_calibration_uses_session_sized_success_goal() -> None:
    args = _build_parser().parse_args(["run"])
    decision = CalibrationDecision(
        status="calibrate",
        should_calibrate=True,
        severity="high",
        reasons=["zero_relevant_ads"],
    )

    plan = _calibration_plan(decision, args, available_targets=50)

    assert plan.tier == "recovery"
    assert plan.target_limit == 50
    assert plan.target_goal == 3


@pytest.mark.parametrize(
    ("tier", "limit", "goal", "effective_goal"),
    [
        ("standard", 20, 10, 10),
        ("low_relevance", 14, 14, 10),
        ("low_relevance", 30, 30, 18),
        ("recovery", 12, 12, 10),
        ("recovery", 27, 27, 17),
        ("recovery", 50, 40, 30),
    ],
)
def test_effective_calibration_goal_tolerates_stale_saved_posts(
    tier,
    limit,
    goal,
    effective_goal,
) -> None:
    plan = SimpleNamespace(
        tier=tier,
        target_limit=limit,
        target_goal=goal,
    )

    assert _effective_calibration_target_goal(plan) == effective_goal


def test_calibrator_command_accepts_deep_calibration_limits(tmp_path) -> None:
    args = _build_parser().parse_args(["run"])
    command = _calibrator_command(
        ProfileConfig(octo_profile_uuid="spain-profile", expected_country="Spain"),
        args,
        tmp_path / "calibration",
        [tmp_path / "ads.relevant.json"],
        "Spain",
        target_limit=50,
        min_successful_targets=40,
        max_reactions=15,
        max_follows=5,
        max_comments=10,
        min_interactions=5,
    )

    assert command[command.index("--limit") + 1] == "50"
    assert command[command.index("--min-successful-targets") + 1] == "40"
    assert command[command.index("--max-reactions") + 1] == "15"
    assert command[command.index("--max-follows") + 1] == "5"
    assert command[command.index("--max-comments") + 1] == "10"
    assert command[command.index("--min-interactions") + 1] == "5"
    assert command[command.index("--timeout-ms") + 1] == "45000"
    assert command[command.index("--landing-view-seconds") + 1] == "45.0"
    assert command[command.index("--landing-timeout-ms") + 1] == "20000"
    assert "--visit-landing" in command
    assert "--offer-funnel" in command
    assert "--direct-offer-fallback" in command
    assert "--repeat-targets-until-deadline" in command
    assert command[command.index("--session-minutes") + 1] == "15.0"
    assert _calibration_timeout_seconds(args, target_limit=50) == 1145


def test_calibration_pass_cap_preserves_unused_targets_for_followup(
    tmp_path,
    monkeypatch,
) -> None:
    root = tmp_path / "orchestrator"
    collect_dir = root / "profiles" / "dominican_profile" / "collect"
    collect_dir.mkdir(parents=True)
    fallback = tmp_path / "fallback.json"
    fallback.write_text(
        json.dumps(
            [
                {
                    "facebook_post_url": f"https://m.facebook.com/100/posts/{index}",
                    "relevance": {"result": "relevant"},
                }
                for index in range(20)
            ]
        ),
        encoding="utf-8",
    )
    profile = ProfileConfig(
        octo_profile_uuid="dominican-profile",
        expected_country="Dominican Republic",
        no_country_filter=True,
        calibration_ads_json=[str(fallback)],
    )
    args = _build_parser().parse_args(["run"])
    captured_command: list[str] = []

    def fake_command(_context, command, log_path, **_kwargs):
        captured_command.extend(command)
        (log_path.parent / "summary.json").write_text(
            json.dumps(
                {
                    "status": "completed",
                    "visited": 7,
                    "ok": 7,
                    "interaction_goal_met": True,
                }
            ),
            encoding="utf-8",
        )
        return 0

    monkeypatch.setattr(
        "app.facebook.orchestration.runtime.context.RuntimeContext.run_command",
        fake_command,
    )
    record = _run_calibration(
        profile,
        args,
        collect_dir,
        root,
        decision=CalibrationDecision(
            status="calibrate",
            should_calibrate=True,
            severity="medium",
            reasons=["proactive_quality_drop"],
        ),
        target_offset=11,
        target_limit_cap=7,
    )

    assert captured_command[captured_command.index("--target-offset") + 1] == "11"
    assert captured_command[captured_command.index("--limit") + 1] == "7"
    assert record["targets_available"] == 20
    assert record["pass_targets_available"] == 7


def test_calibration_paths_require_explicit_relevance(tmp_path) -> None:
    collect_dir = tmp_path / "collect"
    collect_dir.mkdir()
    (collect_dir / "ads.json").write_text(
        json.dumps([{"landing_full": "https://raw.example"}]),
        encoding="utf-8",
    )
    fallback = tmp_path / "fallback.json"
    fallback.write_text(
        json.dumps(
            [
                {
                    "landing_full": "https://relevant.example",
                    "facebook_post_url": "https://m.facebook.com/100/posts/200",
                    "relevance": {"result": "relevant"},
                }
            ]
        ),
        encoding="utf-8",
    )
    profile = ProfileConfig(
        octo_profile_uuid="profile",
        calibration_ads_json=[str(fallback)],
    )

    assert _calibration_ads_paths(profile, collect_dir) == [fallback]


def test_landing_only_history_is_a_funnel_calibration_target(tmp_path) -> None:
    collect_dir = tmp_path / "collect"
    collect_dir.mkdir()
    fallback = tmp_path / "landing-only.json"
    fallback.write_text(
        json.dumps(
            [
                {
                    "country": "Spain",
                    "landing_full": "https://relevant.example",
                    "relevance": {"result": "relevant"},
                }
            ]
        ),
        encoding="utf-8",
    )
    profile = ProfileConfig(
        octo_profile_uuid="profile",
        expected_country="Spain",
        calibration_ads_json=[str(fallback)],
    )

    assert _calibration_ads_paths(profile, collect_dir) == [fallback]
    assert _count_calibration_targets(profile, collect_dir) == 1


def test_quarantined_posts_are_not_counted_as_calibration_targets(tmp_path) -> None:
    collect_dir = tmp_path / "profiles" / "spain_profile" / "collect"
    collect_dir.mkdir(parents=True)
    post_url = "https://m.facebook.com/100/posts/200"
    (collect_dir.parent / "calibration_pool.json").write_text(
        json.dumps(
            [
                {
                    "country": "Spain",
                    "facebook_post_url": post_url,
                    "relevance": {"result": "relevant"},
                }
            ]
        ),
        encoding="utf-8",
    )
    (collect_dir.parent / "calibration_target_health.json").write_text(
        json.dumps(
            {
                "version": 1,
                "targets": {
                    post_url: {
                        "consecutive_failures": 2,
                        "quarantined_until": "2099-01-01T00:00:00+00:00",
                    }
                },
            }
        ),
        encoding="utf-8",
    )
    profile = ProfileConfig(
        octo_profile_uuid="profile",
        expected_country="Spain",
    )

    assert _count_calibration_targets(profile, collect_dir) == 0


def test_two_bad_windows_run_calibration_after_collector_stops(
    tmp_path,
    monkeypatch,
) -> None:
    fallback = tmp_path / "relevant.json"
    fallback.write_text(
        json.dumps(
            [
                {
                    "country": "Spain",
                    "landing_full": f"https://relevant{index}.example",
                    "facebook_post_url": f"https://m.facebook.com/100/posts/{index}",
                    "relevance": {"result": "relevant"},
                }
                for index in range(8)
            ]
        ),
        encoding="utf-8",
    )
    profiles_path = tmp_path / "profiles.json"
    profile = ProfileConfig(
        octo_profile_uuid="spain-profile",
        label="spain",
        expected_country="Spain",
        calibration_ads_json=[str(fallback)],
    )
    profiles_path.write_text(
        json.dumps(
            {
                "profiles": [
                    {
                        "octo_profile_uuid": profile.octo_profile_uuid,
                        "label": profile.label,
                        "expected_country": profile.expected_country,
                        "calibration_ads_json": profile.calibration_ads_json,
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    command_order: list[str] = []

    def fake_command(_context, command, log_path, **_kwargs):
        run_dir = log_path.parent
        if log_path.name == "runner.log":
            command_order.append("collect")
            (run_dir / "run_meta.json").write_text(
                json.dumps(
                    {
                        "octo_profile_uuid": profile.octo_profile_uuid,
                        "profile_country": "Spain",
                    }
                ),
                encoding="utf-8",
            )
            (run_dir / "summary.json").write_text(
                json.dumps(
                    {
                        "elapsed_seconds": 600,
                        "scrolls": 100,
                        "stop_reason": "time_budget",
                        "interest_safe_mode": True,
                        "resolve_enabled": False,
                        "active_actions": {
                            "cta_click_attempts": 0,
                            "video_play_attempts": 0,
                            "comment_open_attempts": 0,
                        },
                        "passive_media_guard": {
                            "installed": True,
                            "init_script_installed": True,
                            "media_route_installed": True,
                        },
                    }
                ),
                encoding="utf-8",
            )
            (run_dir / "ads.json").write_text("[]", encoding="utf-8")
            return 0
        command_order.append("calibrate")
        goal_index = command.index("--min-successful-targets") + 1
        assert command[goal_index] == "3"
        (run_dir / "summary.json").write_text(
            json.dumps(
                {
                    "status": "completed",
                    "targets": 8,
                    "visited": 8,
                    "ok": 8,
                    "failed": 0,
                    "interaction_goal_met": True,
                }
            ),
            encoding="utf-8",
        )
        return 0

    monkeypatch.setattr(
        "app.facebook.orchestration.runtime.context.RuntimeContext.run_command",
        fake_command,
    )
    monkeypatch.setattr(
        "app.facebook.orchestration.runtime.profiles.stop_octo_profile",
        lambda *_args: command_order.append("stop"),
    )
    args = _build_parser().parse_args(
        [
            "run",
            "--profiles-json",
            str(profiles_path),
            "--state-json",
            str(tmp_path / "state.json"),
            "--root-dir",
            str(tmp_path / "root"),
            "--collect-minutes",
            "10",
            "--no-classify-relevance",
        ]
    )
    store = StateStore(tmp_path / "state.json")
    policy = CalibrationPolicy()

    _run_profile_cycle(profile, args, store, policy, tmp_path / "root")
    second_schedule = _run_profile_cycle(
        profile, args, store, policy, tmp_path / "root"
    )
    third_schedule = _run_profile_cycle(profile, args, store, policy, tmp_path / "root")

    assert command_order == [
        "collect",
        "stop",
        "collect",
        "calibrate",
        "stop",
        "collect",
        "calibrate",
        "stop",
    ]
    assert second_schedule.recovery_attempt == 1
    assert third_schedule.recovery_attempt == 2
    _history, _baseline, calibration_timestamps = store.profile_history(
        profile.octo_profile_uuid
    )
    assert len(calibration_timestamps) == 2


def test_relevant_targets_accumulate_in_profile_and_geo_pools(tmp_path) -> None:
    root = tmp_path / "orchestrator"
    collect_dir = root / "profiles" / "spain_profile" / "collect"
    collect_dir.mkdir(parents=True)
    relevant_ads = [
        {
            "fb_ad_id": str(index),
            "country": "Spain",
            "landing_full": f"https://relevant{index}.example",
            "facebook_post_url": f"https://m.facebook.com/100/posts/{index}",
            "relevance": {"result": "relevant"},
        }
        for index in range(3)
    ]
    relevant_ads[-1]["facebook_post_url"] = (
        "https://m.facebook.com/story.php?story_fbid=2&id=100"
    )
    (collect_dir / "ads.relevant.json").write_text(
        json.dumps(relevant_ads),
        encoding="utf-8",
    )
    profile = ProfileConfig(
        octo_profile_uuid="spain-profile",
        expected_country="Spain",
    )

    _update_calibration_pools(profile, collect_dir, root)
    _update_calibration_pools(profile, collect_dir, root)

    profile_pool = collect_dir.parent / "calibration_pool.json"
    geo_pool = root / "calibration_pools" / "spain.json"
    assert len(json.loads(profile_pool.read_text(encoding="utf-8"))) == 3
    assert len(json.loads(geo_pool.read_text(encoding="utf-8"))) == 3
    paths = _calibration_ads_paths(profile, collect_dir, root)
    assert paths == [collect_dir / "ads.relevant.json", profile_pool, geo_pool]


def test_calibration_pool_keeps_relevant_landing_only_records(tmp_path) -> None:
    root = tmp_path / "orchestrator"
    collect_dir = root / "profiles" / "spain_profile" / "collect"
    collect_dir.mkdir(parents=True)
    profile_pool = collect_dir.parent / "calibration_pool.json"
    profile_pool.write_text(
        json.dumps(
            [
                {
                    "country": "Spain",
                    "landing_full": "https://landing-only.example",
                    "relevance": {"result": "relevant"},
                }
            ]
        ),
        encoding="utf-8",
    )
    profile = ProfileConfig(
        octo_profile_uuid="spain-profile",
        expected_country="Spain",
    )

    _update_calibration_pools(profile, collect_dir, root)

    assert json.loads(profile_pool.read_text(encoding="utf-8")) == [
        {
            "country": "Spain",
            "landing_full": "https://landing-only.example",
            "relevance": {"result": "relevant"},
        }
    ]


def test_watch_run_does_not_lower_mature_baseline() -> None:
    policy = CalibrationPolicy()
    records = []
    for index, ads_per_hour in enumerate((200.0, 190.0, 210.0)):
        metrics = RunMetrics(
            run_dir=f"healthy-{index}",
            profile_country="Spain",
            geo_observed=True,
            ads_total=40,
            target_ads=10,
            ads_per_hour=ads_per_hour,
            target_per_hour=50,
        )
        records.append({"baseline_candidate": True, "metrics": metrics.to_dict()})
    degraded = RunMetrics(
        run_dir="watch",
        profile_country="Spain",
        geo_observed=True,
        ads_total=10,
        target_ads=5,
        ads_per_hour=50,
        target_per_hour=25,
    )
    records.append({"baseline_candidate": False, "metrics": degraded.to_dict()})

    baseline = _baseline_from_run_records(records, policy)

    assert baseline.sample_count == 3
    assert baseline.ads_per_hour == 200


def test_public_discovery_adds_profile_once_and_geo_can_be_adopted(
    tmp_path,
    monkeypatch,
) -> None:
    profiles_path = tmp_path / "profiles.json"
    profiles_path.write_text('{"profiles": []}', encoding="utf-8")
    monkeypatch.setattr(
        "app.facebook.orchestration.runtime.profiles.public_profile_payloads",
        lambda _token, _tags: [
            {
                "uuid": "new-profile",
                "title": "New Facebook profile",
                "extra_info": {},
            }
        ],
    )

    assert (
        _merge_public_profiles(
            profiles_path,
            token="token",
            search_tags="facebook-tag",
            enable_new=True,
        )
        == 1
    )
    assert (
        _merge_public_profiles(
            profiles_path,
            token="token",
            search_tags="facebook-tag",
            enable_new=True,
        )
        == 0
    )
    _persist_profile_country(profiles_path, "new-profile", "Spain")

    profiles = _load_profiles(profiles_path)
    assert len(profiles) == 1
    assert profiles[0].enabled is True
    assert profiles[0].expected_country == "Spain"

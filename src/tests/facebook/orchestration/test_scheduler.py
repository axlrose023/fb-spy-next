from __future__ import annotations

import time
from collections.abc import Callable

import pytest

from app.facebook.orchestration import (
    ProfileCycleSchedule,
    ProfileScheduler,
    SchedulerConfig,
    SchedulerHooks,
)
from app.facebook.profiles import Profile

pytestmark = pytest.mark.unit


class ScheduleState:
    def __init__(self, schedule: ProfileCycleSchedule | None = None) -> None:
        self._schedule = schedule

    def profile_last_run_at(self, _profile_uuid: str) -> str | None:
        return None

    def profile_resume_schedule(
        self,
        _profile_uuid: str,
        *,
        default_rest_seconds: float,
    ) -> ProfileCycleSchedule:
        return self._schedule or ProfileCycleSchedule(
            kind="normal",
            rest_seconds=default_rest_seconds,
        )


def config(
    *,
    max_cycles: int = 0,
    default_rest_seconds: float = 0,
) -> SchedulerConfig:
    return SchedulerConfig(
        max_parallel=2,
        default_rest_seconds=default_rest_seconds,
        infrastructure_retry_seconds=300,
        discovery_interval_seconds=0,
        max_cycles=max_cycles,
        poll_interval_seconds=0,
    )


def scheduler(
    *,
    active_config: SchedulerConfig,
    state: ScheduleState,
    hooks: SchedulerHooks,
    stop_requested: Callable[[], bool] = lambda: False,
    monotonic: Callable[[], float] = lambda: 0,
    sleep: Callable[[float], None] = lambda _seconds: time.sleep(0.001),
) -> ProfileScheduler:
    return ProfileScheduler(
        active_config,
        state,
        hooks,
        stop_requested=stop_requested,
        monotonic=monotonic,
        sleep=sleep,
    )


def test_run_once_reports_empty_profile_catalog() -> None:
    logs: list[str] = []
    hooks = SchedulerHooks(
        discover_profiles=lambda: None,
        enabled_profiles=list,
        run_profile_cycle=lambda _profile: None,
        remaining_profile_rest_seconds=lambda _uuid, _rest: 0,
        log=logs.append,
        log_schedule=lambda _profile, _schedule: None,
    )

    result = scheduler(
        active_config=config(),
        state=ScheduleState(),
        hooks=hooks,
    ).run_once()

    assert result == 1
    assert logs == ["No enabled profiles."]


def test_run_once_isolates_profile_failure_and_preserves_stop_code() -> None:
    profiles = [Profile(octo_profile_uuid="ok"), Profile(octo_profile_uuid="failed")]
    logs: list[str] = []

    def run_cycle(profile: Profile) -> None:
        if profile.octo_profile_uuid == "failed":
            raise RuntimeError("cycle failure")

    hooks = SchedulerHooks(
        discover_profiles=lambda: None,
        enabled_profiles=lambda: profiles,
        run_profile_cycle=run_cycle,
        remaining_profile_rest_seconds=lambda _uuid, _rest: 0,
        log=logs.append,
        log_schedule=lambda _profile, _schedule: None,
    )

    failed = scheduler(
        active_config=config(),
        state=ScheduleState(),
        hooks=hooks,
    ).run_once()
    stopped = scheduler(
        active_config=config(),
        state=ScheduleState(),
        hooks=hooks,
        stop_requested=lambda: True,
    ).run_once()

    assert failed == 1
    assert stopped == 130
    assert any("cycle failure" in message for message in logs)


def test_continuous_scheduler_restores_profile_rest_before_starting() -> None:
    profile = Profile(octo_profile_uuid="spain", label="Spain")
    logs: list[str] = []
    stopped = False

    def request_stop(_seconds: float) -> None:
        nonlocal stopped
        stopped = True

    hooks = SchedulerHooks(
        discover_profiles=lambda: None,
        enabled_profiles=lambda: [profile],
        run_profile_cycle=lambda _profile: pytest.fail("profile started too early"),
        remaining_profile_rest_seconds=lambda _uuid, _rest: 600,
        log=logs.append,
        log_schedule=lambda _profile, _schedule: None,
    )

    result = scheduler(
        active_config=config(default_rest_seconds=600),
        state=ScheduleState(ProfileCycleSchedule(kind="normal", rest_seconds=600)),
        hooks=hooks,
        stop_requested=lambda: stopped,
        monotonic=lambda: 100,
        sleep=request_stop,
    ).run_continuously()

    assert result == 130
    assert "[Spain] resume schedule=normal rest=10.0m" in logs
    assert logs[-1] == "[orchestrator] stopping; waiting for active profile jobs"


def test_cycle_failure_uses_infrastructure_retry_schedule() -> None:
    profile = Profile(octo_profile_uuid="failed-profile")
    logs: list[str] = []
    schedules: list[ProfileCycleSchedule] = []

    def fail_cycle(_profile: Profile) -> None:
        raise RuntimeError("failed")

    hooks = SchedulerHooks(
        discover_profiles=lambda: None,
        enabled_profiles=lambda: [profile],
        run_profile_cycle=fail_cycle,
        remaining_profile_rest_seconds=lambda _uuid, _rest: 0,
        log=logs.append,
        log_schedule=lambda _profile, schedule: schedules.append(schedule),
    )

    result = scheduler(
        active_config=config(max_cycles=1),
        state=ScheduleState(),
        hooks=hooks,
    ).run_continuously()

    assert result == 0
    assert schedules == [
        ProfileCycleSchedule(kind="infrastructure_retry", rest_seconds=300)
    ]
    assert any("failed-p cycle failed" in message for message in logs)


def test_continuous_discovery_starts_new_profile_without_restarting() -> None:
    first = Profile(octo_profile_uuid="first")
    second = Profile(octo_profile_uuid="second")
    discovery_count = 0
    started: list[str] = []
    clock_value = 0.0

    def discover() -> None:
        nonlocal discovery_count
        discovery_count += 1

    def profiles() -> list[Profile]:
        return [first] if discovery_count == 1 else [first, second]

    def run_cycle(profile: Profile) -> ProfileCycleSchedule:
        started.append(profile.octo_profile_uuid)
        return ProfileCycleSchedule(kind="normal", rest_seconds=1_000)

    def monotonic() -> float:
        nonlocal clock_value
        clock_value += 10
        return clock_value

    hooks = SchedulerHooks(
        discover_profiles=discover,
        enabled_profiles=profiles,
        run_profile_cycle=run_cycle,
        remaining_profile_rest_seconds=lambda _uuid, _rest: 0,
        log=lambda _message: None,
        log_schedule=lambda _profile, _schedule: None,
    )

    result = scheduler(
        active_config=config(max_cycles=2),
        state=ScheduleState(),
        hooks=hooks,
        monotonic=monotonic,
    ).run_continuously()

    assert result == 0
    assert discovery_count >= 2
    assert started == ["first", "second"]

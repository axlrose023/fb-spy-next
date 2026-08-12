from __future__ import annotations

import concurrent.futures
from collections.abc import Callable

from app.facebook.profiles import Profile

from ..contracts import ProfileScheduleState
from ..models import ProfileCycleSchedule
from .capacity import select_due_profile_ids
from .models import SchedulerConfig, SchedulerHooks


class ProfileScheduler:
    def __init__(
        self,
        config: SchedulerConfig,
        state: ProfileScheduleState,
        hooks: SchedulerHooks,
        *,
        stop_requested: Callable[[], bool],
        monotonic: Callable[[], float],
        sleep: Callable[[float], None],
    ) -> None:
        self._config = config
        self._state = state
        self._hooks = hooks
        self._stop_requested = stop_requested
        self._monotonic = monotonic
        self._sleep = sleep

    def run_once(self) -> int:
        profiles = self._hooks.enabled_profiles()
        if not profiles:
            self._hooks.log("No enabled profiles.")
            return 1
        failed = False
        with concurrent.futures.ThreadPoolExecutor(
            max_workers=self._config.max_parallel
        ) as executor:
            futures = [
                executor.submit(self._hooks.run_profile_cycle, profile)
                for profile in profiles
            ]
            for future in concurrent.futures.as_completed(futures):
                try:
                    future.result()
                except Exception as exc:
                    failed = True
                    self._hooks.log(f"[orchestrator] profile cycle failed: {exc!r}")
        if self._stop_requested():
            return 130
        return 1 if failed else 0

    def run_continuously(self) -> int:
        next_due: dict[str, float] = {}
        running: dict[
            str,
            concurrent.futures.Future[ProfileCycleSchedule | None],
        ] = {}
        profiles: dict[str, Profile] = {}
        next_discovery = 0.0
        completed_cycles = 0
        executor = concurrent.futures.ThreadPoolExecutor(
            max_workers=self._config.max_parallel
        )
        try:
            while not self._stop_requested():
                now = self._monotonic()
                if now >= next_discovery:
                    try:
                        self._hooks.discover_profiles()
                        profiles = {
                            profile.octo_profile_uuid: profile
                            for profile in self._hooks.enabled_profiles()
                        }
                        self._restore_new_profile_schedules(
                            profiles,
                            next_due,
                            now=now,
                        )
                    finally:
                        next_discovery = now + max(
                            5.0,
                            self._config.discovery_interval_seconds,
                        )

                for profile_uuid, future in list(running.items()):
                    if not future.done():
                        continue
                    del running[profile_uuid]
                    schedule = self._completed_schedule(profile_uuid, future)
                    next_due[profile_uuid] = self._monotonic() + schedule.rest_seconds
                    profile = profiles.get(profile_uuid)
                    if profile is not None:
                        self._hooks.log_schedule(profile, schedule)
                    completed_cycles += 1
                    if (
                        self._config.max_cycles > 0
                        and completed_cycles >= self._config.max_cycles
                    ):
                        return 0

                due_profile_ids = select_due_profile_ids(
                    profiles,
                    running_profile_ids=running,
                    next_due=next_due,
                    now=now,
                    max_parallel=self._config.max_parallel,
                )
                if self._config.max_cycles > 0:
                    remaining_slots = max(
                        0,
                        self._config.max_cycles - completed_cycles - len(running),
                    )
                    due_profile_ids = due_profile_ids[:remaining_slots]
                for profile_uuid in due_profile_ids:
                    profile = profiles[profile_uuid]
                    running[profile_uuid] = executor.submit(
                        self._hooks.run_profile_cycle,
                        profile,
                    )

                if not profiles and not running:
                    self._hooks.log(
                        "[orchestrator] no enabled profiles; waiting for discovery"
                    )
                self._sleep(self._config.poll_interval_seconds)
            self._hooks.log("[orchestrator] stopping; waiting for active profile jobs")
            return 130
        finally:
            executor.shutdown(wait=True, cancel_futures=True)

    def _restore_new_profile_schedules(
        self,
        profiles: dict[str, Profile],
        next_due: dict[str, float],
        *,
        now: float,
    ) -> None:
        for profile_uuid, profile in profiles.items():
            if profile_uuid in next_due:
                continue
            schedule = self._state.profile_resume_schedule(
                profile_uuid,
                default_rest_seconds=self._config.default_rest_seconds,
            )
            remaining_rest = self._hooks.remaining_profile_rest_seconds(
                profile_uuid,
                schedule.rest_seconds,
            )
            next_due[profile_uuid] = now + remaining_rest
            if remaining_rest > 0:
                self._hooks.log(
                    f"[{profile.display_name}] resume "
                    f"schedule={schedule.kind} rest={remaining_rest / 60:.1f}m"
                )

    def _completed_schedule(
        self,
        profile_uuid: str,
        future: concurrent.futures.Future[ProfileCycleSchedule | None],
    ) -> ProfileCycleSchedule:
        schedule = ProfileCycleSchedule(
            kind="normal",
            rest_seconds=self._config.default_rest_seconds,
        )
        try:
            result = future.result()
            if isinstance(result, ProfileCycleSchedule):
                schedule = result
        except Exception as exc:
            schedule = ProfileCycleSchedule(
                kind="infrastructure_retry",
                rest_seconds=self._config.infrastructure_retry_seconds,
            )
            self._hooks.log(
                f"[orchestrator] profile {profile_uuid[:8]} cycle failed: {exc!r}"
            )
        return schedule

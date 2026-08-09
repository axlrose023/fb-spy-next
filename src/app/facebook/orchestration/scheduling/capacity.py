from __future__ import annotations

from collections.abc import Collection, Iterable, Mapping


def available_profile_slots(*, max_parallel: int, running_count: int) -> int:
    if max_parallel < 1:
        raise ValueError("max_parallel must be at least 1")
    if running_count < 0:
        raise ValueError("running_count cannot be negative")
    return max(0, max_parallel - running_count)


def select_due_profile_ids(
    profile_ids: Iterable[str],
    *,
    running_profile_ids: Collection[str],
    next_due: Mapping[str, float],
    now: float,
    max_parallel: int,
) -> tuple[str, ...]:
    available = available_profile_slots(
        max_parallel=max_parallel,
        running_count=len(running_profile_ids),
    )
    if available == 0:
        return ()
    due_profile_ids = (
        profile_id
        for profile_id in profile_ids
        if profile_id not in running_profile_ids
        and next_due.get(profile_id, 0.0) <= now
    )
    return tuple(
        sorted(due_profile_ids, key=lambda profile_id: next_due.get(profile_id, 0.0))[
            :available
        ]
    )

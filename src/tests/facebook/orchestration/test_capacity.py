from __future__ import annotations

import random

import pytest

from app.facebook.orchestration import (
    available_profile_slots,
    select_due_profile_ids,
)

pytestmark = pytest.mark.unit


@pytest.mark.parametrize("max_parallel", [1, 5, 10])
def test_available_slots_scale_with_configured_capacity(max_parallel: int) -> None:
    assert available_profile_slots(max_parallel=max_parallel, running_count=0) == (
        max_parallel
    )
    assert (
        available_profile_slots(
            max_parallel=max_parallel,
            running_count=max_parallel,
        )
        == 0
    )


def test_available_slots_reject_invalid_counts() -> None:
    with pytest.raises(ValueError, match="max_parallel"):
        available_profile_slots(max_parallel=0, running_count=0)
    with pytest.raises(ValueError, match="running_count"):
        available_profile_slots(max_parallel=1, running_count=-1)


def test_due_profiles_are_ordered_and_limited_without_running_profiles() -> None:
    selected = select_due_profile_ids(
        ["later", "running", "oldest", "future", "same-due"],
        running_profile_ids={"running"},
        next_due={
            "later": 8.0,
            "running": 1.0,
            "oldest": 2.0,
            "future": 11.0,
            "same-due": 8.0,
        },
        now=10.0,
        max_parallel=3,
    )

    assert selected == ("oldest", "later")


def test_equal_due_time_preserves_profile_catalog_order() -> None:
    selected = select_due_profile_ids(
        ["first", "second", "third"],
        running_profile_ids=(),
        next_due={},
        now=0.0,
        max_parallel=2,
    )

    assert selected == ("first", "second")


def test_due_selection_matches_legacy_scheduler_for_valid_states() -> None:
    generator = random.Random(1203)
    for _ in range(2_000):
        profile_ids = [f"profile-{index}" for index in range(generator.randint(0, 20))]
        max_parallel = generator.randint(1, 10)
        running_count = generator.randint(0, min(max_parallel, len(profile_ids)))
        running = set(generator.sample(profile_ids, running_count))
        next_due = {
            profile_id: generator.uniform(-100, 100) for profile_id in profile_ids
        }
        now = generator.uniform(-100, 100)
        available = max_parallel - len(running)
        legacy_due = sorted(
            (
                profile_id
                for profile_id in profile_ids
                if profile_id not in running and next_due.get(profile_id, 0.0) <= now
            ),
            key=lambda profile_id: next_due.get(profile_id, 0.0),
        )

        assert select_due_profile_ids(
            profile_ids,
            running_profile_ids=running,
            next_due=next_due,
            now=now,
            max_parallel=max_parallel,
        ) == tuple(legacy_due[:available])

from __future__ import annotations

from datetime import UTC, datetime

from ..models import RecoverySchedulePolicy


def profile_rest_seconds(
    *,
    cycle_sleep_seconds: float,
    profile_rest_minutes: float,
) -> float:
    return max(
        0.0,
        float(cycle_sleep_seconds),
        float(profile_rest_minutes) * 60.0,
    )


def recovery_schedule_policy(
    *,
    cycle_sleep_seconds: float,
    profile_rest_minutes: float,
    recovery_burst_cycles: int,
    recovery_burst_rest_minutes: float,
    infrastructure_retry_minutes: float,
) -> RecoverySchedulePolicy:
    return RecoverySchedulePolicy(
        normal_rest_seconds=profile_rest_seconds(
            cycle_sleep_seconds=cycle_sleep_seconds,
            profile_rest_minutes=profile_rest_minutes,
        ),
        burst_limit=max(1, int(recovery_burst_cycles)),
        burst_rest_seconds=max(0.0, float(recovery_burst_rest_minutes) * 60.0),
        infrastructure_retry_seconds=max(
            0.0,
            float(infrastructure_retry_minutes) * 60.0,
        ),
    )


def remaining_profile_rest_seconds(
    last_run_at: str | None,
    rest_seconds: float,
    *,
    now: datetime | None = None,
) -> float:
    if not last_run_at or rest_seconds <= 0:
        return 0.0
    try:
        parsed = datetime.fromisoformat(last_run_at.replace("Z", "+00:00"))
    except ValueError:
        return 0.0
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    elapsed = max(
        0.0,
        ((now or datetime.now(UTC)) - parsed.astimezone(UTC)).total_seconds(),
    )
    return max(0.0, rest_seconds - elapsed)

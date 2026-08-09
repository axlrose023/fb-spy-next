from __future__ import annotations

from datetime import datetime, timedelta

from app.facebook.runs import RunMetrics, parse_datetime

from ..models import CalibrationPolicy
from .windows import (
    is_valid_observation_window,
    is_valid_relevance_window,
    same_relevance_series,
)

FAST_RECOVERY_REASONS = frozenset(
    {
        "zero_ads_repeated",
        "zero_relevant_ads",
        "one_relevant_ad",
        "relevance_rate_below_minimum",
        "too_few_relevant_ads",
    }
)


def calibration_timing_blockers(
    reasons: list[str],
    *,
    last_calibration_at: str | datetime | None,
    attempts: list[str | datetime],
    history: list[RunMetrics],
    now: datetime,
    policy: CalibrationPolicy,
) -> list[str]:
    blockers: list[str] = []
    cooldown_seconds = policy.calibration_cooldown_seconds
    if FAST_RECOVERY_REASONS.intersection(reasons):
        cooldown_seconds = policy.zero_ads_calibration_cooldown_seconds
    elif "periodic_account_maintenance" in reasons:
        cooldown_seconds = policy.maintenance_calibration_interval_seconds

    effective_cooldown = cooldown_active(
        last_calibration_at,
        now,
        policy,
        cooldown_seconds=cooldown_seconds,
    )
    if effective_cooldown:
        blockers.append("calibration_cooldown")
    if (
        not effective_cooldown
        and attempts
        and retry_cooldown_active(attempts[-1], now, policy)
    ):
        blockers.append("calibration_retry_cooldown")
    if "zero_ads_repeated" in reasons:
        zero_ads_attempts = attempts_after_last_nonzero_run(attempts, history)
        if zero_ads_backoff_active(zero_ads_attempts, now, policy):
            blockers.append("zero_ads_calibration_backoff")
    return blockers


def cooldown_active(
    last_calibration_at: str | datetime | None,
    now: datetime,
    policy: CalibrationPolicy,
    *,
    cooldown_seconds: float | None = None,
) -> bool:
    last = parse_datetime(last_calibration_at)
    if not last:
        return False
    seconds = (
        policy.calibration_cooldown_seconds
        if cooldown_seconds is None
        else cooldown_seconds
    )
    return bool(now - last < timedelta(seconds=seconds))


def retry_cooldown_active(
    last_attempt_at: str | datetime | None,
    now: datetime,
    policy: CalibrationPolicy,
) -> bool:
    last = parse_datetime(last_attempt_at)
    return bool(
        last
        and now - last < timedelta(seconds=policy.calibration_retry_cooldown_seconds)
    )


def maintenance_calibration_due(
    current: RunMetrics,
    history: list[RunMetrics],
    *,
    last_calibration_at: str | datetime | None,
    now: datetime,
    policy: CalibrationPolicy,
) -> bool:
    interval = policy.maintenance_calibration_interval_seconds
    if interval <= 0 or current.ads_total <= 0:
        return False

    valid_runs: list[RunMetrics] = []
    for run in [current, *reversed(history)]:
        if run is not current and not same_relevance_series(current, run):
            break
        if not is_valid_observation_window(
            run, policy
        ) and not is_valid_relevance_window(run, policy):
            break
        valid_runs.append(run)
    if len(valid_runs) < policy.maintenance_min_valid_windows:
        return False

    last_calibration = parse_datetime(last_calibration_at)
    if last_calibration is not None:
        return bool(now - last_calibration >= timedelta(seconds=interval))

    first_observation = min(
        (
            timestamp
            for run in valid_runs
            for timestamp in [
                parse_datetime(run.finished_at),
                parse_datetime(run.started_at),
            ]
            if timestamp is not None
        ),
        default=None,
    )
    return first_observation is not None and now - first_observation >= timedelta(
        seconds=interval
    )


def attempts_after_last_nonzero_run(
    attempts: list[str | datetime],
    history: list[RunMetrics],
) -> list[datetime]:
    parsed_attempts = sorted(
        timestamp
        for timestamp in (parse_datetime(value) for value in attempts)
        if timestamp is not None
    )
    recovered_at = max(
        (
            timestamp
            for run in history
            if run.ads_total > 0
            for timestamp in [parse_datetime(run.finished_at)]
            if timestamp is not None
        ),
        default=None,
    )
    if recovered_at is None:
        return parsed_attempts
    return [timestamp for timestamp in parsed_attempts if timestamp > recovered_at]


def zero_ads_backoff_active(
    attempts: list[datetime],
    now: datetime,
    policy: CalibrationPolicy,
) -> bool:
    limit = policy.zero_ads_calibration_burst_limit
    backoff_seconds = policy.zero_ads_calibration_backoff_seconds
    if limit < 1 or backoff_seconds <= 0:
        return False
    eligible = sorted(timestamp for timestamp in attempts if timestamp <= now)
    if len(eligible) < limit:
        return False

    burst_count = 1
    newer = eligible[-1]
    for older in reversed(eligible[:-1]):
        if newer - older >= timedelta(seconds=backoff_seconds):
            break
        burst_count += 1
        newer = older
    return burst_count >= limit and now - eligible[-1] < timedelta(
        seconds=backoff_seconds
    )


def daily_limit_reached(
    calibration_timestamps: list[str | datetime],
    now: datetime,
    policy: CalibrationPolicy,
) -> bool:
    since = now - timedelta(hours=24)
    recent = [
        timestamp
        for timestamp in (parse_datetime(value) for value in calibration_timestamps)
        if timestamp and timestamp >= since
    ]
    return len(recent) >= policy.max_calibrations_per_24h

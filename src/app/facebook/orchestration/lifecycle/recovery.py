from __future__ import annotations

import math
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

from app.facebook.profiles import Profile
from app.facebook.runs import RunMetrics


@dataclass(frozen=True, slots=True)
class RecoveryCycleResult:
    records: tuple[dict[str, Any], ...]
    next_target_offset: int
    remaining_targets: int


class RecoveryCycleCoordinator:
    def run(
        self,
        *,
        planned_passes: int,
        remaining_daily_attempts: int,
        available_targets: int,
        target_offset: int,
        min_targets: int,
        stop_requested: Callable[[], bool],
        execute_pass: Callable[[int, int], dict[str, Any]],
        log_followup: Callable[[int, int, int], None],
    ) -> RecoveryCycleResult:
        passes = min(planned_passes, remaining_daily_attempts)
        remaining_targets = available_targets
        records: list[dict[str, Any]] = []
        for pass_index in range(passes):
            if stop_requested() or remaining_targets < min_targets:
                break
            target_limit_cap = calibration_pass_target_cap(
                remaining_targets,
                passes_left=passes - pass_index,
                min_targets=min_targets,
            )
            record = execute_pass(target_offset, target_limit_cap)
            record["pass_index"] = pass_index + 1
            record["planned_passes"] = passes
            records.append(record)
            consumed = calibration_targets_consumed(record)
            target_offset += consumed
            remaining_targets = max(0, remaining_targets - consumed)
            if pass_index + 1 >= passes:
                break
            if not calibration_allows_followup(record):
                break
            log_followup(pass_index + 2, passes, remaining_targets)
        return RecoveryCycleResult(
            records=tuple(records),
            next_target_offset=target_offset,
            remaining_targets=remaining_targets,
        )


def calibration_passes_for_cycle(
    profile: Profile,
    metrics: RunMetrics,
    history: list[RunMetrics],
    *,
    recovery_active: bool,
) -> int:
    configured = max(1, profile.failed_recovery_calibration_passes)
    if configured == 1 or not recovery_active:
        return 1
    previous = next(
        (
            item
            for item in reversed(history)
            if item.target_source == "relevance"
            and item.relevance_known
            and item.relevance_classified_ads > 0
            and (
                not metrics.profile_uuid
                or not item.profile_uuid
                or metrics.profile_uuid == item.profile_uuid
            )
        ),
        None,
    )
    if previous is None:
        return 1
    return (
        1 if relevance_result_meaningfully_improved(metrics, previous) else configured
    )


def relevance_result_meaningfully_improved(
    current: RunMetrics,
    previous: RunMetrics,
) -> bool:
    current_relevant = int(current.relevant_ads or 0)
    previous_relevant = int(previous.relevant_ads or 0)
    count_gain = current_relevant - previous_relevant
    required_count_gain = max(2, math.ceil(previous_relevant * 0.20))
    if count_gain >= required_count_gain:
        return True
    if (
        current.relevant_rate is not None
        and previous.relevant_rate is not None
        and current.relevant_rate >= previous.relevant_rate + 0.05
    ):
        return True
    return bool(
        current.target_per_hour is not None
        and previous.target_per_hour is not None
        and previous.target_per_hour > 0
        and current.target_per_hour >= previous.target_per_hour * 1.20
    )


def remaining_daily_calibration_attempts(
    timestamps: list[str],
    *,
    limit: int,
    now: datetime | None = None,
) -> int:
    now_dt = now or datetime.now(UTC)
    since = now_dt - timedelta(hours=24)
    recent = 0
    for value in timestamps:
        try:
            parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        except ValueError:
            continue
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=UTC)
        if parsed >= since:
            recent += 1
    return max(0, max(1, limit) - recent)


def calibration_pass_target_cap(
    remaining_targets: int,
    *,
    passes_left: int,
    min_targets: int,
) -> int:
    remaining = max(0, remaining_targets)
    passes = max(1, passes_left)
    minimum = max(1, min_targets)
    if passes == 1 or remaining < passes * minimum:
        return remaining
    return max(minimum, math.ceil(remaining / passes))


def calibration_targets_consumed(calibration: dict[str, Any]) -> int:
    summary = _calibration_summary(calibration)
    value = summary.get("visited") or calibration.get("target_limit") or 0
    try:
        return max(0, int(value))
    except (TypeError, ValueError):
        return 0


def calibration_allows_followup(calibration: dict[str, Any]) -> bool:
    summary = _calibration_summary(calibration)
    return bool(
        summary.get("status") in {"completed", "dry_run"}
        and not summary.get("infrastructure_error")
        and calibration_targets_consumed(calibration) > 0
    )


def _calibration_summary(calibration: dict[str, Any]) -> dict[str, Any]:
    raw_summary = calibration.get("summary")
    return raw_summary if isinstance(raw_summary, dict) else {}

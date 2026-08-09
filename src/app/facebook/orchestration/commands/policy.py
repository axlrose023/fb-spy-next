from __future__ import annotations

from dataclasses import replace
from typing import Any

from app.facebook.calibration import CalibrationPolicy


def calibration_policy_from_args(args: Any) -> CalibrationPolicy:
    if args.calibration_cooldown_hours < 0:
        raise ValueError("--calibration-cooldown-hours cannot be negative")
    if args.soft_drop_calibration_windows < 2:
        raise ValueError("--soft-drop-calibration-windows must be at least 2")
    if not 0 < args.watch_drop_ratio <= 1:
        raise ValueError("--watch-drop-ratio must be greater than 0 and at most 1")
    if not 0 < args.immediate_drop_ratio <= 1:
        raise ValueError("--immediate-drop-ratio must be greater than 0 and at most 1")
    if not 0 < args.minimum_healthy_relevant_rate <= 1:
        raise ValueError(
            "--minimum-healthy-relevant-rate must be greater than 0 and at most 1"
        )
    if args.minimum_healthy_relevant_ads < 1:
        raise ValueError("--minimum-healthy-relevant-ads must be at least 1")
    if args.zero_ads_windows < 1:
        raise ValueError("--zero-ads-windows must be at least 1")
    if args.absolute_low_ads_windows < 1:
        raise ValueError("--absolute-low-ads-windows must be at least 1")
    if args.absolute_low_ads_per_hour < 0:
        raise ValueError("--absolute-low-ads-per-hour cannot be negative")
    if args.zero_ads_calibration_cooldown_minutes < 0:
        raise ValueError("--zero-ads-calibration-cooldown-minutes cannot be negative")
    if args.zero_ads_calibration_burst_limit < 1:
        raise ValueError("--zero-ads-calibration-burst-limit must be at least 1")
    if args.zero_ads_calibration_backoff_hours < 0:
        raise ValueError("--zero-ads-calibration-backoff-hours cannot be negative")
    if args.calibration_retry_cooldown_hours < 0:
        raise ValueError("--calibration-retry-cooldown-hours cannot be negative")
    if args.maintenance_calibration_hours < 0:
        raise ValueError("--maintenance-calibration-hours cannot be negative")
    if args.maintenance_min_valid_windows < 1:
        raise ValueError("--maintenance-min-valid-windows must be at least 1")
    if args.max_calibrations_per_24h < 1:
        raise ValueError("--max-calibrations-per-24h must be at least 1")
    return replace(
        CalibrationPolicy(),
        zero_ads_windows=args.zero_ads_windows,
        absolute_low_ads_windows=args.absolute_low_ads_windows,
        absolute_low_ads_per_hour=args.absolute_low_ads_per_hour,
        soft_drop_calibration_windows=args.soft_drop_calibration_windows,
        watch_drop_ratio=args.watch_drop_ratio,
        immediate_drop_ratio=args.immediate_drop_ratio,
        minimum_healthy_relevant_rate=args.minimum_healthy_relevant_rate,
        minimum_healthy_relevant_ads=args.minimum_healthy_relevant_ads,
        calibration_cooldown_seconds=args.calibration_cooldown_hours * 60 * 60,
        zero_ads_calibration_cooldown_seconds=(
            args.zero_ads_calibration_cooldown_minutes * 60
        ),
        zero_ads_calibration_burst_limit=args.zero_ads_calibration_burst_limit,
        zero_ads_calibration_backoff_seconds=(
            args.zero_ads_calibration_backoff_hours * 60 * 60
        ),
        calibration_retry_cooldown_seconds=(
            args.calibration_retry_cooldown_hours * 60 * 60
        ),
        maintenance_calibration_interval_seconds=(
            args.maintenance_calibration_hours * 60 * 60
        ),
        maintenance_min_valid_windows=args.maintenance_min_valid_windows,
        max_calibrations_per_24h=args.max_calibrations_per_24h,
        min_calibration_targets=args.min_calibration_targets,
        min_successful_calibration_targets=args.min_calibration_targets,
    )

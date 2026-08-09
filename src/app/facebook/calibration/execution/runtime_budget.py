from __future__ import annotations

from typing import Protocol


class CalibrationRuntimeOptions(Protocol):
    calibration_offer_funnel: bool
    calibration_session_minutes: float
    calibration_page_timeout: float
    calibration_landing_timeout: float
    calibration_timeout_grace: float
    calibration_view_seconds: float
    calibration_pause: float
    calibration_locate_timeout: float
    calibration_landing_view_seconds: float
    calibration_visit_landing: bool
    calibration_limit: int


def calibration_timeout_seconds(
    options: CalibrationRuntimeOptions,
    *,
    target_limit: int | None = None,
) -> float:
    if options.calibration_offer_funnel and options.calibration_session_minutes > 0:
        return max(
            300.0,
            options.calibration_session_minutes * 60
            + options.calibration_page_timeout
            + options.calibration_landing_timeout
            + options.calibration_timeout_grace,
        )
    per_target = (
        options.calibration_view_seconds
        + options.calibration_pause
        + options.calibration_locate_timeout
        + options.calibration_page_timeout
        + (
            options.calibration_landing_view_seconds
            + options.calibration_landing_timeout
            if options.calibration_visit_landing
            else 0.0
        )
        + 3.0
    )
    return max(
        300.0,
        (target_limit if target_limit is not None else options.calibration_limit)
        * per_target
        + options.calibration_timeout_grace,
    )

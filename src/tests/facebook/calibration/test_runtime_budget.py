from __future__ import annotations

from dataclasses import dataclass

import pytest

from app.facebook.calibration import calibration_timeout_seconds

pytestmark = pytest.mark.unit


@dataclass
class RuntimeOptions:
    calibration_offer_funnel: bool = False
    calibration_session_minutes: float = 0
    calibration_page_timeout: float = 45
    calibration_landing_timeout: float = 20
    calibration_timeout_grace: float = 180
    calibration_view_seconds: float = 45
    calibration_pause: float = 2
    calibration_locate_timeout: float = 12
    calibration_landing_view_seconds: float = 45
    calibration_visit_landing: bool = True
    calibration_limit: int = 20


def test_funnel_budget_uses_session_and_navigation_grace() -> None:
    options = RuntimeOptions(
        calibration_offer_funnel=True,
        calibration_session_minutes=15,
    )

    assert calibration_timeout_seconds(options) == 1145


def test_funnel_budget_keeps_five_minute_floor() -> None:
    options = RuntimeOptions(
        calibration_offer_funnel=True,
        calibration_session_minutes=1,
        calibration_page_timeout=1,
        calibration_landing_timeout=1,
        calibration_timeout_grace=1,
    )

    assert calibration_timeout_seconds(options) == 300


def test_per_target_budget_includes_landing_only_when_enabled() -> None:
    options = RuntimeOptions(calibration_limit=2, calibration_timeout_grace=0)
    without_landing = RuntimeOptions(
        calibration_limit=2,
        calibration_timeout_grace=0,
        calibration_visit_landing=False,
    )

    assert calibration_timeout_seconds(options) == 344
    assert calibration_timeout_seconds(without_landing) == 300
    assert calibration_timeout_seconds(options, target_limit=50) == 8600
    assert calibration_timeout_seconds(without_landing, target_limit=50) == 5350


def test_zero_explicit_limit_differs_from_default_limit() -> None:
    options = RuntimeOptions(calibration_limit=50, calibration_timeout_grace=500)

    assert calibration_timeout_seconds(options, target_limit=0) == 500
    assert calibration_timeout_seconds(options) > 500

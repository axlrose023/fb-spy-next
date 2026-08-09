from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import pytest

from app.facebook.orchestration import validate_orchestration_run_options

pytestmark = pytest.mark.unit


@dataclass
class RunOptions:
    max_parallel: int = 1
    profile_rest_minutes: float = 0
    recovery_burst_cycles: int = 1
    recovery_burst_rest_minutes: float = 0
    infrastructure_retry_minutes: float = 0
    calibration_limit: int = 1
    calibration_target_goal: int = 1
    calibration_low_relevance_target_goal: int = 1
    calibration_recovery_target_goal: int = 1
    calibration_recovery_target_limit: int = 1
    calibration_page_timeout: float = 1
    calibration_landing_view_seconds: float = 0
    calibration_landing_timeout: float = 1
    calibration_session_minutes: float = 0
    calibration_funnel_target_goal: int = 1
    calibration_prelander_max_scrolls: int = 0
    calibration_quiz_max_questions: int = 0
    calibration_offer_success_wait_seconds: float = 0
    calibration_max_retained_offer_tabs: int = 1
    calibration_offer_submit_mode: str = "disabled"
    calibration_offer_submit_allow_domain: list[str] = field(default_factory=list)
    calibration_offer_identity_json: str = ""
    min_calibration_targets: int = 1


@pytest.mark.parametrize(
    ("overrides", "message"),
    [
        ({"max_parallel": 0}, "--max-parallel must be at least 1"),
        (
            {"profile_rest_minutes": -0.1},
            "--profile-rest-minutes cannot be negative",
        ),
        (
            {"recovery_burst_cycles": 0},
            "--recovery-burst-cycles must be at least 1",
        ),
        (
            {"recovery_burst_rest_minutes": -0.1},
            "--recovery-burst-rest-minutes cannot be negative",
        ),
        (
            {"infrastructure_retry_minutes": -0.1},
            "--infrastructure-retry-minutes cannot be negative",
        ),
        ({"calibration_limit": 0}, "--calibration-limit must be at least 1"),
        (
            {"calibration_target_goal": 0},
            "--calibration-target-goal must be at least 1",
        ),
        (
            {"calibration_low_relevance_target_goal": 0},
            "--calibration-low-relevance-target-goal must be at least 1",
        ),
        (
            {"calibration_recovery_target_goal": 0},
            "--calibration-recovery-target-goal must be at least 1",
        ),
        (
            {
                "calibration_recovery_target_goal": 2,
                "calibration_recovery_target_limit": 1,
            },
            "--calibration-recovery-target-limit must be at least "
            "--calibration-recovery-target-goal",
        ),
        (
            {"calibration_page_timeout": 0},
            "--calibration-page-timeout must be greater than 0",
        ),
        (
            {"calibration_landing_view_seconds": -0.1},
            "--calibration-landing-view-seconds cannot be negative",
        ),
        (
            {"calibration_landing_timeout": 0},
            "--calibration-landing-timeout must be greater than 0",
        ),
        (
            {"calibration_session_minutes": -0.1},
            "--calibration-session-minutes cannot be negative",
        ),
        (
            {"calibration_funnel_target_goal": 0},
            "--calibration-funnel-target-goal must be at least 1",
        ),
        (
            {"calibration_prelander_max_scrolls": -1},
            "--calibration-prelander-max-scrolls cannot be negative",
        ),
        (
            {"calibration_quiz_max_questions": -1},
            "--calibration-quiz-max-questions cannot be negative",
        ),
        (
            {"calibration_offer_success_wait_seconds": -0.1},
            "--calibration-offer-success-wait-seconds cannot be negative",
        ),
        (
            {"calibration_max_retained_offer_tabs": 0},
            "--calibration-max-retained-offer-tabs must be at least 1",
        ),
        (
            {
                "calibration_offer_submit_mode": "allowlisted",
                "calibration_offer_submit_allow_domain": [],
            },
            "allowlisted offer submit requires --calibration-offer-submit-allow-domain",
        ),
        (
            {
                "calibration_offer_submit_mode": "allowlisted",
                "calibration_offer_submit_allow_domain": ["offer.example"],
                "calibration_offer_identity_json": "",
            },
            "allowlisted offer submit requires --calibration-offer-identity-json",
        ),
        (
            {"min_calibration_targets": 0},
            "--min-calibration-targets must be at least 1",
        ),
    ],
)
def test_invalid_run_options_preserve_exact_error(
    overrides: dict[str, Any],
    message: str,
) -> None:
    options = RunOptions()
    for name, value in overrides.items():
        setattr(options, name, value)

    with pytest.raises(ValueError, match=f"^{message}$"):
        validate_orchestration_run_options(options)


def test_boundary_values_are_valid() -> None:
    validate_orchestration_run_options(RunOptions())


def test_allowlisted_submit_accepts_domain_and_identity() -> None:
    options = RunOptions(
        calibration_offer_submit_mode="allowlisted",
        calibration_offer_submit_allow_domain=["offer.example"],
        calibration_offer_identity_json="identity.json",
    )

    validate_orchestration_run_options(options)

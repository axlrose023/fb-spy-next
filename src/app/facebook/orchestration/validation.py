from __future__ import annotations

from typing import Protocol


class OrchestrationRunOptions(Protocol):
    max_parallel: int
    profile_rest_minutes: float
    recovery_burst_cycles: int
    recovery_burst_rest_minutes: float
    infrastructure_retry_minutes: float
    calibration_limit: int
    calibration_target_goal: int
    calibration_low_relevance_target_goal: int
    calibration_recovery_target_goal: int
    calibration_recovery_target_limit: int
    calibration_page_timeout: float
    calibration_landing_view_seconds: float
    calibration_landing_timeout: float
    calibration_session_minutes: float
    calibration_funnel_target_goal: int
    calibration_prelander_max_scrolls: int
    calibration_quiz_max_questions: int
    calibration_offer_success_wait_seconds: float
    calibration_max_retained_offer_tabs: int
    calibration_offer_submit_mode: str
    calibration_offer_submit_allow_domain: list[str]
    calibration_offer_identity_json: str
    min_calibration_targets: int


def validate_orchestration_run_options(options: OrchestrationRunOptions) -> None:
    if options.max_parallel < 1:
        raise ValueError("--max-parallel must be at least 1")
    if options.profile_rest_minutes < 0:
        raise ValueError("--profile-rest-minutes cannot be negative")
    if options.recovery_burst_cycles < 1:
        raise ValueError("--recovery-burst-cycles must be at least 1")
    if options.recovery_burst_rest_minutes < 0:
        raise ValueError("--recovery-burst-rest-minutes cannot be negative")
    if options.infrastructure_retry_minutes < 0:
        raise ValueError("--infrastructure-retry-minutes cannot be negative")
    if options.calibration_limit < 1:
        raise ValueError("--calibration-limit must be at least 1")
    if options.calibration_target_goal < 1:
        raise ValueError("--calibration-target-goal must be at least 1")
    if options.calibration_low_relevance_target_goal < 1:
        raise ValueError("--calibration-low-relevance-target-goal must be at least 1")
    if options.calibration_recovery_target_goal < 1:
        raise ValueError("--calibration-recovery-target-goal must be at least 1")
    if (
        options.calibration_recovery_target_limit
        < options.calibration_recovery_target_goal
    ):
        raise ValueError(
            "--calibration-recovery-target-limit must be at least "
            "--calibration-recovery-target-goal"
        )
    if options.calibration_page_timeout <= 0:
        raise ValueError("--calibration-page-timeout must be greater than 0")
    if options.calibration_landing_view_seconds < 0:
        raise ValueError("--calibration-landing-view-seconds cannot be negative")
    if options.calibration_landing_timeout <= 0:
        raise ValueError("--calibration-landing-timeout must be greater than 0")
    if options.calibration_session_minutes < 0:
        raise ValueError("--calibration-session-minutes cannot be negative")
    if options.calibration_funnel_target_goal < 1:
        raise ValueError("--calibration-funnel-target-goal must be at least 1")
    if options.calibration_prelander_max_scrolls < 0:
        raise ValueError("--calibration-prelander-max-scrolls cannot be negative")
    if options.calibration_quiz_max_questions < 0:
        raise ValueError("--calibration-quiz-max-questions cannot be negative")
    if options.calibration_offer_success_wait_seconds < 0:
        raise ValueError("--calibration-offer-success-wait-seconds cannot be negative")
    if options.calibration_max_retained_offer_tabs < 1:
        raise ValueError("--calibration-max-retained-offer-tabs must be at least 1")
    if options.calibration_offer_submit_mode == "allowlisted":
        if not options.calibration_offer_submit_allow_domain:
            raise ValueError(
                "allowlisted offer submit requires "
                "--calibration-offer-submit-allow-domain"
            )
        if not options.calibration_offer_identity_json:
            raise ValueError(
                "allowlisted offer submit requires --calibration-offer-identity-json"
            )
    if options.min_calibration_targets < 1:
        raise ValueError("--min-calibration-targets must be at least 1")

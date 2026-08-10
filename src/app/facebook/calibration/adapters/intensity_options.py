from __future__ import annotations

from typing import Protocol

from ..models import CalibrationDecision, CalibrationPlan
from ..planning import CalibrationIntensityPolicy, plan_calibration_intensity


class CalibrationIntensityOptions(Protocol):
    calibration_limit: int
    calibration_target_goal: int
    calibration_recovery_target_limit: int
    calibration_recovery_target_goal: int
    calibration_low_relevance_target_goal: int
    calibration_offer_funnel: bool
    calibration_funnel_target_goal: int
    calibration_max_reactions: int
    calibration_max_follows: int
    calibration_max_comments: int
    calibration_min_interactions: int
    calibration_comment_every: int


def calibration_plan_from_options(
    decision: CalibrationDecision,
    options: CalibrationIntensityOptions,
    *,
    available_targets: int,
) -> CalibrationPlan:
    policy = CalibrationIntensityPolicy(
        standard_limit=options.calibration_limit,
        standard_goal=options.calibration_target_goal,
        recovery_limit=options.calibration_recovery_target_limit,
        recovery_goal=options.calibration_recovery_target_goal,
        low_relevance_goal=options.calibration_low_relevance_target_goal,
        funnel_enabled=options.calibration_offer_funnel,
        funnel_goal=options.calibration_funnel_target_goal,
        max_reactions=options.calibration_max_reactions,
        max_follows=options.calibration_max_follows,
        max_comments=options.calibration_max_comments,
        min_interactions=options.calibration_min_interactions,
        comment_every=options.calibration_comment_every,
    )
    return plan_calibration_intensity(
        decision,
        policy,
        available_targets=available_targets,
    )

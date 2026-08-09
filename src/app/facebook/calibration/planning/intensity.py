from __future__ import annotations

import math
from dataclasses import dataclass

from ..models import CalibrationDecision, CalibrationPlan

RECOVERY_REASONS = frozenset({"zero_ads_repeated", "zero_relevant_ads"})
LOW_RELEVANCE_REASONS = frozenset(
    {
        "one_relevant_ad",
        "proactive_quality_drop",
        "relevance_rate_below_minimum",
        "relevance_rate_too_low",
        "too_few_relevant_ads",
    }
)


@dataclass(frozen=True, slots=True)
class CalibrationIntensityPolicy:
    standard_limit: int
    standard_goal: int
    recovery_limit: int
    recovery_goal: int
    low_relevance_goal: int
    funnel_enabled: bool
    funnel_goal: int
    max_reactions: int
    max_follows: int
    max_comments: int
    min_interactions: int
    comment_every: int


def plan_calibration_intensity(
    decision: CalibrationDecision,
    policy: CalibrationIntensityPolicy,
    *,
    available_targets: int,
) -> CalibrationPlan:
    reasons = set(decision.reasons)
    if reasons.intersection(RECOVERY_REASONS):
        tier = "recovery"
        desired_goal = policy.recovery_goal
        desired_limit = policy.recovery_limit
    elif reasons.intersection(LOW_RELEVANCE_REASONS):
        tier = "low_relevance"
        desired_goal = policy.low_relevance_goal
        desired_limit = desired_goal
    else:
        tier = "standard"
        desired_goal = policy.standard_goal
        desired_limit = max(policy.standard_limit, desired_goal)

    if policy.funnel_enabled:
        desired_goal = min(desired_goal, policy.funnel_goal)

    target_limit = min(max(0, available_targets), desired_limit)
    target_goal = min(target_limit, desired_goal)
    if tier == "standard":
        return CalibrationPlan(
            tier=tier,
            target_limit=target_limit,
            target_goal=target_goal,
            max_reactions=policy.max_reactions,
            max_follows=policy.max_follows,
            max_comments=policy.max_comments,
            min_interactions=policy.min_interactions,
        )

    max_comments = policy.max_comments
    if policy.comment_every > 0:
        max_comments = max(
            max_comments,
            min(10, math.ceil(target_limit / policy.comment_every)),
        )
    return CalibrationPlan(
        tier=tier,
        target_limit=target_limit,
        target_goal=target_goal,
        max_reactions=max(policy.max_reactions, math.ceil(target_limit * 0.30)),
        max_follows=max(policy.max_follows, math.ceil(target_limit * 0.10)),
        max_comments=max_comments,
        min_interactions=max(
            policy.min_interactions,
            math.ceil(target_limit * 0.10),
        ),
    )


def effective_target_goal(plan: CalibrationPlan) -> int:
    if plan.tier == "standard" or plan.target_limit <= 10:
        return plan.target_goal
    return min(
        plan.target_goal,
        max(10, math.ceil(plan.target_limit * 0.60)),
    )

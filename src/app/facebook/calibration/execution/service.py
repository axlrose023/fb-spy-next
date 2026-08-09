from __future__ import annotations

from collections.abc import Callable, Mapping

from .models import EngagementPlan, EngagementPolicy


def plan_engagement(
    policy: EngagementPolicy,
    budget: Mapping[str, int],
    *,
    relevant_ad_number: int,
    comments_available: bool,
    visit_landing: bool,
    random_value: Callable[[], float],
) -> EngagementPlan:
    """Choose bounded interactions while preserving lazy probability draws."""
    force_minimum = budget.get("successful", 0) < policy.min_interactions
    reaction_due = budget.get("reaction", 0) < policy.max_reactions and (
        force_minimum or random_value() < policy.reaction_rate
    )
    comment_due = (
        comments_available
        and policy.comments_enabled
        and budget.get("comment", 0) < policy.max_comments
        and relevant_ad_number % policy.comment_every == 0
    )
    follow_due = (
        budget.get("follow", 0) < policy.max_follows
        and random_value() < policy.follow_rate
    )
    return EngagementPlan(
        reaction=reaction_due,
        comment=comment_due,
        follow=follow_due,
        landing_visit=visit_landing,
    )

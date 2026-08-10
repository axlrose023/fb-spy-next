from __future__ import annotations

import pytest

from app.facebook.calibration import EngagementPolicy, plan_engagement
from app.facebook.calibration.cli import build_parser as build_calibration_parser
from app.facebook.orchestration.commands import (
    build_parser as build_orchestration_parser,
)

pytestmark = pytest.mark.unit


def test_minimum_interaction_forces_reaction_without_consuming_its_draw() -> None:
    draws: list[float] = []

    def random_value() -> float:
        draws.append(0.99)
        return draws[-1]

    plan = plan_engagement(
        EngagementPolicy(
            reaction_rate=0.0,
            follow_rate=0.0,
            comment_every=0,
            max_reactions=1,
            max_follows=1,
            max_comments=0,
            min_interactions=1,
        ),
        {"reaction": 0, "follow": 0, "comment": 0, "successful": 0},
        relevant_ad_number=1,
        comments_available=True,
        visit_landing=False,
        random_value=random_value,
    )

    assert plan.reaction is True
    assert plan.follow is False
    assert draws == [0.99]


def test_action_caps_skip_probability_draws_and_keep_due_comment() -> None:
    def unexpected_draw() -> float:
        raise AssertionError("capped interactions must not consume random values")

    plan = plan_engagement(
        EngagementPolicy(
            reaction_rate=1.0,
            follow_rate=1.0,
            comment_every=2,
            max_reactions=1,
            max_follows=1,
            max_comments=2,
            min_interactions=0,
        ),
        {"reaction": 1, "follow": 1, "comment": 0, "successful": 1},
        relevant_ad_number=2,
        comments_available=True,
        visit_landing=True,
        random_value=unexpected_draw,
    )

    assert plan.due_actions() == ("comment", "landing_visit")


@pytest.mark.parametrize(
    ("comment_every", "max_comments"),
    [(0, 5), (2, 0)],
)
def test_comments_remain_disabled_when_either_guard_is_zero(
    comment_every: int,
    max_comments: int,
) -> None:
    plan = plan_engagement(
        EngagementPolicy(
            reaction_rate=0.0,
            follow_rate=0.0,
            comment_every=comment_every,
            max_reactions=0,
            max_follows=0,
            max_comments=max_comments,
            min_interactions=0,
        ),
        {},
        relevant_ad_number=2,
        comments_available=True,
        visit_landing=False,
        random_value=lambda: 1.0,
    )

    assert plan.comment is False


def test_engagement_policy_defaults_are_preserved() -> None:
    policy = EngagementPolicy()

    assert (policy.comment_every, policy.max_comments) == (2, 5)


def test_comments_are_disabled_by_default_in_runtime_entrypoints() -> None:
    calibration_args = build_calibration_parser().parse_args([])
    orchestration_args = build_orchestration_parser().parse_args(["run"])

    assert (calibration_args.comment_every, calibration_args.max_comments) == (0, 0)
    assert (
        orchestration_args.calibration_comment_every,
        orchestration_args.calibration_max_comments,
    ) == (0, 0)

from __future__ import annotations

import pytest

from app.facebook.calibration import (
    CalibrationDecision,
    CalibrationIntensityPolicy,
    CalibrationPolicy,
    evaluate_calibration_need,
    plan_calibration_intensity,
    select_calibration_targets,
)
from app.facebook.runs import RunMetrics

pytestmark = pytest.mark.unit


def test_zero_relevance_is_an_immediate_recovery_signal() -> None:
    metrics = RunMetrics(
        run_dir="/tmp/run",
        profile_country="Canada",
        expected_country="Canada",
        return_code=0,
        elapsed_seconds=900,
        scrolls=300,
        ads_total=20,
        geo_observed=True,
        geo_match=True,
        relevance_known=True,
        relevance_classified_ads=20,
        relevance_coverage=1.0,
        relevant_ads=0,
        relevant_rate=0.0,
        target_source="relevance",
    )

    decision = evaluate_calibration_need(metrics, policy=CalibrationPolicy())

    assert decision.should_calibrate is True
    assert "zero_relevant_ads" in decision.reasons


def test_recovery_intensity_scales_to_available_target_pool() -> None:
    plan = plan_calibration_intensity(
        CalibrationDecision(
            status="calibrate",
            should_calibrate=True,
            severity="high",
            reasons=["zero_relevant_ads"],
        ),
        CalibrationIntensityPolicy(
            standard_limit=20,
            standard_goal=10,
            recovery_limit=50,
            recovery_goal=40,
            low_relevance_goal=30,
            funnel_enabled=False,
            funnel_goal=3,
            max_reactions=5,
            max_follows=2,
            max_comments=0,
            min_interactions=2,
            comment_every=0,
        ),
        available_targets=36,
    )

    assert plan.tier == "recovery"
    assert (plan.target_limit, plan.target_goal) == (36, 36)
    assert (plan.max_reactions, plan.max_follows) == (11, 4)


def test_target_pool_prioritizes_evidence_and_limits_domain_first() -> None:
    targets = select_calibration_targets(
        [
            {
                "advertiser": "Old",
                "landing_full": "https://same.example/old",
                "captured_at": "2026-01-01T00:00:00+00:00",
            },
            {
                "advertiser": "Strong",
                "landing_full": "https://same.example/strong",
                "fb_ad_id": "123",
                "has_video": True,
                "captured_at": "2026-02-01T00:00:00+00:00",
            },
            {
                "advertiser": "Other",
                "landing_full": "https://other.example/offer",
                "captured_at": "2026-01-15T00:00:00+00:00",
            },
        ],
        limit=2,
        max_per_domain=1,
    )

    assert [target.advertiser for target in targets] == ["Strong", "Other"]

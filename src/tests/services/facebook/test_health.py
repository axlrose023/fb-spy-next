import json
from datetime import UTC, datetime, timedelta

import pytest

from app.facebook.calibration import (
    CalibrationPolicy,
    baseline_from_history,
    evaluate_calibration_need,
    is_good_baseline_candidate,
)
from app.facebook.profiles import MetricBaseline
from app.facebook.runs import RunMetrics, collect_run_metrics

pytestmark = pytest.mark.unit


def test_collect_run_metrics_computes_spain_baseline_shape(tmp_path) -> None:
    run_dir = tmp_path / "spain"
    run_dir.mkdir()
    (run_dir / "run_meta.json").write_text(
        json.dumps(
            {
                "octo_profile_uuid": "spain-profile",
                "profile_country": "Spain",
                "octo_ip": "5.159.171.33",
                "started_at": "2026-07-09T11:00:00+00:00",
            }
        ),
        encoding="utf-8",
    )
    (run_dir / "summary.json").write_text(
        json.dumps(
            {
                "elapsed_seconds": 900,
                "scrolls": 300,
                "refreshes": 1,
                "stop_reason": "time_budget",
            }
        ),
        encoding="utf-8",
    )
    ads = []
    for index in range(51):
        is_link = index < 22
        has_landing = index < 21
        ads.append(
            {
                "advertiser": f"Brand {index}",
                "ad_type": "link" if is_link else "video",
                "country": "Spain",
                "displayed_domain": f"domain{index % 20}.example",
                "landing_clean": f"https://landing{index}.example/path"
                if has_landing
                else None,
                "fb_ad_id": str(index) if has_landing else None,
                "screenshot": f"screens/{index}.png",
                "screenshot_ok": True,
            }
        )
    (run_dir / "ads.json").write_text(json.dumps(ads), encoding="utf-8")

    metrics = collect_run_metrics(run_dir, expected_country="Spain")

    assert metrics.ads_total == 51
    assert metrics.resolved_landings == 21
    assert metrics.ads_per_hour == 204
    assert metrics.target_per_hour == 84
    assert metrics.ads_per_100_scrolls == 17
    assert metrics.stop_reason == "time_budget"
    assert metrics.geo_match is True
    assert is_good_baseline_candidate(metrics, CalibrationPolicy())


def test_repeated_zero_ads_triggers_calibration() -> None:
    policy = CalibrationPolicy()
    baseline = MetricBaseline(
        sample_count=1, window_seconds=900, ads_per_hour=200, target_per_hour=80
    )
    previous = [_metrics(ads_total=0, target_ads=0)]
    current = _metrics(ads_total=0, target_ads=0)

    decision = evaluate_calibration_need(
        current,
        history=previous,
        baseline=baseline,
        policy=policy,
    )

    assert decision.should_calibrate is True
    assert "zero_ads_repeated" in decision.reasons


def test_baseline_from_old_collector_version_is_not_compared() -> None:
    baseline = MetricBaseline(
        sample_count=3,
        collector_metric_version=1,
        window_seconds=900,
        octo_headless=False,
        trusted=True,
        ads_per_hour=200,
        target_per_hour=80,
    )
    old_shape = _metrics(ads_total=10, target_ads=5)
    current = RunMetrics(
        **{
            **old_shape.to_dict(),
            "collector_metric_version": 2,
        }
    )
    previous = RunMetrics(
        **{
            **old_shape.to_dict(),
            "run_dir": "/tmp/previous",
            "collector_metric_version": 2,
        }
    )

    decision = evaluate_calibration_need(
        current,
        history=[previous],
        baseline=baseline,
    )

    assert decision.should_calibrate is False
    assert "baseline_metric_version_mismatch" in decision.observations


def test_failed_zero_ads_window_does_not_count_toward_calibration() -> None:
    policy = CalibrationPolicy()
    baseline = MetricBaseline(
        sample_count=3,
        window_seconds=900,
        target_source="relevance",
        target_sample_count=3,
        ads_per_hour=200,
        target_per_hour=80,
    )
    failed_previous = _metrics(ads_total=0, target_ads=0)
    failed_previous = RunMetrics(**{**failed_previous.to_dict(), "return_code": 1})
    current = _metrics(ads_total=0, target_ads=0)

    decision = evaluate_calibration_need(
        current,
        history=[failed_previous],
        baseline=baseline,
        policy=policy,
    )

    assert decision.should_calibrate is False
    assert decision.consecutive["zero_ads"] == 1


def test_interrupted_zero_ads_window_does_not_count_toward_calibration() -> None:
    policy = CalibrationPolicy()
    baseline = MetricBaseline(
        sample_count=3, window_seconds=900, ads_per_hour=200, target_per_hour=80
    )
    previous = [_metrics(ads_total=0, target_ads=0)]
    current = _metrics(ads_total=0, target_ads=0, stop_reason="interrupted")

    decision = evaluate_calibration_need(
        current,
        history=previous,
        baseline=baseline,
        policy=policy,
    )

    assert decision.should_calibrate is False
    assert decision.consecutive["zero_ads"] == 0
    assert "collector_stop_reason_interrupted" in decision.blockers


def test_interrupted_good_run_is_not_baseline_candidate() -> None:
    metrics = _metrics(ads_total=50, target_ads=25, stop_reason="interrupted")

    assert is_good_baseline_candidate(metrics, CalibrationPolicy()) is False


@pytest.mark.parametrize(
    "stop_reason",
    [
        "resolve_timeout",
        "video_timeout",
        "octo_proxy_error",
        "octo_start_error",
        "facebook_login_required",
    ],
)
def test_operation_timeout_is_not_a_health_or_baseline_window(stop_reason) -> None:
    metrics = _metrics(ads_total=1, target_ads=0, stop_reason=stop_reason)

    decision = evaluate_calibration_need(
        metrics,
        history=[_metrics(ads_total=0, target_ads=0)],
        policy=CalibrationPolicy(),
    )

    assert is_good_baseline_candidate(metrics, CalibrationPolicy()) is False
    assert decision.should_calibrate is False
    assert f"collector_stop_reason_{stop_reason}" in decision.blockers


def test_resolve_timeout_with_classified_ads_can_trigger_relevance_calibration() -> (
    None
):
    low = _metrics(
        ads_total=75,
        target_ads=0,
        target_source="relevance",
        relevance_known=True,
        relevant_ads=0,
        relevant_rate=0.0,
        stop_reason="resolve_timeout",
    )
    low = RunMetrics(
        **{
            **low.to_dict(),
            "elapsed_seconds": 420,
        }
    )

    decision = evaluate_calibration_need(
        low,
        history=[low],
        policy=CalibrationPolicy(min_relevance_classified_total=50),
    )

    assert decision.should_calibrate is True
    assert "relevance_rate_too_low" in decision.reasons
    assert "collector_stop_reason_resolve_timeout" not in decision.blockers
    assert "insufficient_elapsed_time" not in decision.blockers
    assert is_good_baseline_candidate(low, CalibrationPolicy()) is False


def test_login_required_never_becomes_relevance_signal() -> None:
    low = _metrics(
        ads_total=25,
        target_ads=0,
        target_source="relevance",
        relevance_known=True,
        relevant_ads=0,
        relevant_rate=0.0,
        stop_reason="facebook_login_required",
    )

    decision = evaluate_calibration_need(low, history=[low])

    assert decision.should_calibrate is False
    assert "collector_stop_reason_facebook_login_required" in decision.blockers


def test_low_relevant_rate_bypasses_baseline_comparison() -> None:
    policy = CalibrationPolicy()
    baseline = MetricBaseline(
        sample_count=3,
        window_seconds=900,
        target_source="relevance",
        target_sample_count=3,
        ads_per_hour=200,
        target_per_hour=80,
        relevant_rate=0.25,
    )
    previous = [
        _metrics(
            ads_total=200,
            target_ads=1,
            target_source="relevance",
            relevance_known=True,
            relevant_ads=1,
            relevant_rate=0.005,
        )
    ]
    current = _metrics(
        ads_total=200,
        target_ads=1,
        target_source="relevance",
        relevance_known=True,
        relevant_ads=1,
        relevant_rate=0.005,
    )

    decision = evaluate_calibration_need(
        current,
        history=previous,
        baseline=baseline,
        policy=policy,
    )

    assert decision.should_calibrate is True
    assert "relevant_ads_per_hour_below_baseline" not in decision.reasons
    assert "relevance_rate_too_low" in decision.reasons
    assert "one_relevant_ad" in decision.reasons


def test_relevance_below_absolute_floor_does_not_use_baseline() -> None:
    policy = CalibrationPolicy()
    baseline = MetricBaseline(
        sample_count=3,
        window_seconds=900,
        target_source="relevance",
        target_sample_count=3,
        ads_per_hour=200,
        target_per_hour=24,
        relevant_rate=0.117647,
    )
    previous = [
        _metrics(
            ads_total=40,
            target_ads=3,
            target_source="relevance",
            relevance_known=True,
            relevant_ads=3,
            relevant_rate=0.075,
        )
    ]
    current = _metrics(
        ads_total=40,
        target_ads=3,
        target_source="relevance",
        relevance_known=True,
        relevant_ads=3,
        relevant_rate=0.075,
    )

    decision = evaluate_calibration_need(
        current,
        history=previous,
        baseline=baseline,
        policy=policy,
    )

    assert decision.should_calibrate is True
    assert "relevance_rate_below_minimum" in decision.reasons
    assert "relevant_yield_30pct_drop" not in decision.reasons


def test_low_relevance_calibrates_without_waiting_for_confidence() -> None:
    policy = CalibrationPolicy()
    low_run = _metrics(
        ads_total=200,
        target_ads=2,
        target_source="relevance",
        relevance_known=True,
        relevant_ads=2,
        relevant_rate=0.01,
    )

    decision = evaluate_calibration_need(
        low_run,
        policy=policy,
    )

    assert decision.should_calibrate is True
    assert "relevance_rate_below_minimum" in decision.reasons


@pytest.mark.parametrize(
    ("relevant_ads", "classified_ads"),
    [
        (2, 20),
        (14, 20),
    ],
)
def test_relevance_below_seventy_five_percent_calibrates_immediately(
    relevant_ads,
    classified_ads,
) -> None:
    current = _metrics(
        ads_total=classified_ads,
        target_ads=relevant_ads,
        target_source="relevance",
        relevance_known=True,
        relevant_ads=relevant_ads,
        relevant_rate=relevant_ads / classified_ads,
    )

    decision = evaluate_calibration_need(current)

    assert decision.should_calibrate is True
    assert "relevance_rate_below_minimum" in decision.reasons


@pytest.mark.parametrize("relevant_ads", [2, 10, 14])
def test_too_few_relevant_ads_calibrates_even_at_one_hundred_percent(
    relevant_ads,
) -> None:
    current = _metrics(
        ads_total=relevant_ads,
        target_ads=relevant_ads,
        target_source="relevance",
        relevance_known=True,
        relevant_ads=relevant_ads,
        relevant_rate=1.0,
    )

    decision = evaluate_calibration_need(current)

    assert decision.should_calibrate is True
    assert "too_few_relevant_ads" in decision.reasons


def test_seventy_five_percent_can_be_compared_with_baseline() -> None:
    baseline = MetricBaseline(
        sample_count=3,
        window_seconds=900,
        target_source="relevance",
        target_sample_count=3,
        ads_per_hour=80,
        target_per_hour=100,
        relevant_rate=1.0,
    )
    current = _metrics(
        ads_total=20,
        target_ads=15,
        target_source="relevance",
        relevance_known=True,
        relevant_ads=15,
        relevant_rate=0.75,
    )

    decision = evaluate_calibration_need(current, baseline=baseline)

    assert decision.should_calibrate is True
    assert "relevance_rate_below_minimum" not in decision.reasons
    assert "relevant_yield_30pct_drop" in decision.reasons


def test_seventy_five_percent_without_baseline_does_not_calibrate() -> None:
    current = _metrics(
        ads_total=20,
        target_ads=15,
        target_source="relevance",
        relevance_known=True,
        relevant_ads=15,
        relevant_rate=0.75,
    )

    decision = evaluate_calibration_need(current)

    assert decision.should_calibrate is False


def test_one_zero_relevance_run_triggers_calibration() -> None:
    current = _metrics(
        ads_total=34,
        target_ads=0,
        target_source="relevance",
        relevance_known=True,
        relevant_ads=0,
        relevant_rate=0.0,
    )

    decision = evaluate_calibration_need(current)

    assert decision.should_calibrate is True
    assert "zero_relevant_ads" in decision.reasons


def test_small_zero_relevance_run_also_triggers_calibration() -> None:
    current = _metrics(
        ads_total=10,
        target_ads=0,
        target_source="relevance",
        relevance_known=True,
        relevant_ads=0,
        relevant_rate=0.0,
    )

    decision = evaluate_calibration_need(current)

    assert decision.should_calibrate is True
    assert "zero_relevant_ads" in decision.reasons


def test_one_relevant_ad_triggers_without_baseline() -> None:
    current = _metrics(
        ads_total=36,
        target_ads=1,
        target_source="relevance",
        relevance_known=True,
        relevant_ads=1,
        relevant_rate=1 / 36,
    )

    decision = evaluate_calibration_need(current)

    assert decision.should_calibrate is True
    assert "one_relevant_ad" in decision.reasons


def test_zero_relevance_uses_short_recalibration_cooldown() -> None:
    now = datetime(2026, 7, 20, 12, tzinfo=UTC)
    current = _metrics(
        ads_total=10,
        target_ads=0,
        target_source="relevance",
        relevance_known=True,
        relevant_ads=0,
        relevant_rate=0.0,
    )

    blocked = evaluate_calibration_need(
        current,
        last_calibration_at=now - timedelta(minutes=20),
        now=now,
    )
    ready = evaluate_calibration_need(
        current,
        last_calibration_at=now - timedelta(minutes=31),
        now=now,
    )

    assert blocked.should_calibrate is False
    assert "calibration_cooldown" in blocked.blockers
    assert ready.should_calibrate is True


def test_low_resolved_landings_without_relevance_is_only_observation() -> None:
    policy = CalibrationPolicy()
    baseline = MetricBaseline(
        sample_count=3,
        window_seconds=900,
        target_source="resolved_landings",
        target_sample_count=3,
        ads_per_hour=200,
        target_per_hour=80,
    )
    previous = [_metrics(ads_total=40, target_ads=1)]
    current = _metrics(ads_total=42, target_ads=1)

    decision = evaluate_calibration_need(
        current,
        history=previous,
        baseline=baseline,
        policy=policy,
    )

    assert decision.should_calibrate is False
    assert "resolved_landings_per_hour_below_baseline" in decision.observations


def test_geo_mismatch_blocks_calibration_and_requires_review() -> None:
    policy = CalibrationPolicy()
    baseline = MetricBaseline(
        sample_count=3, window_seconds=900, ads_per_hour=200, target_per_hour=80
    )
    current = _metrics(ads_total=0, target_ads=0, geo_match=False)

    decision = evaluate_calibration_need(
        current,
        history=[_metrics(ads_total=0, target_ads=0, geo_match=False)],
        baseline=baseline,
        policy=policy,
    )

    assert decision.should_calibrate is False
    assert decision.status == "manual_review"
    assert "profile_geo_mismatch" in decision.blockers


def test_unknown_profile_geo_blocks_calibration() -> None:
    current = _metrics(ads_total=0, target_ads=0)
    current = RunMetrics(**{**current.to_dict(), "geo_observed": False})

    decision = evaluate_calibration_need(
        current,
        history=[_metrics(ads_total=0, target_ads=0)],
        baseline=MetricBaseline(sample_count=3, window_seconds=900, ads_per_hour=200),
    )

    assert decision.should_calibrate is False
    assert "profile_geo_unknown" in decision.blockers


def test_failed_calibration_attempt_has_short_retry_cooldown() -> None:
    now = datetime(2026, 7, 10, tzinfo=UTC)
    current = _metrics(ads_total=0, target_ads=0)

    decision = evaluate_calibration_need(
        current,
        history=[_metrics(ads_total=0, target_ads=0)],
        baseline=MetricBaseline(sample_count=3, window_seconds=900, ads_per_hour=200),
        calibration_attempt_timestamps=[now - timedelta(minutes=30)],
        now=now,
    )

    assert decision.should_calibrate is False
    assert "calibration_retry_cooldown" in decision.blockers


def test_calibration_defaults_allow_repeated_zero_ad_recovery() -> None:
    policy = CalibrationPolicy()

    assert policy.zero_ads_windows == 2
    assert policy.absolute_low_ads_windows == 2
    assert policy.absolute_low_ads_per_hour == 12
    assert policy.soft_drop_calibration_windows == 3
    assert policy.calibration_cooldown_seconds == 60 * 60
    assert policy.zero_ads_calibration_cooldown_seconds == 30 * 60
    assert policy.zero_ads_calibration_burst_limit == 8
    assert policy.zero_ads_calibration_backoff_seconds == 2 * 60 * 60
    assert policy.maintenance_calibration_interval_seconds == 6 * 60 * 60
    assert policy.maintenance_min_valid_windows == 3
    assert policy.max_calibrations_per_24h == 24
    assert policy.min_calibration_targets == 3


def test_zero_ads_uses_shorter_cooldown_than_quality_drop() -> None:
    now = datetime(2026, 7, 10, tzinfo=UTC)
    current = _metrics(ads_total=0, target_ads=0)
    policy = CalibrationPolicy(zero_ads_windows=1)

    blocked = evaluate_calibration_need(
        current,
        baseline=MetricBaseline(sample_count=3, window_seconds=900, ads_per_hour=200),
        policy=policy,
        last_calibration_at=now - timedelta(minutes=20),
        now=now,
    )
    ready = evaluate_calibration_need(
        current,
        baseline=MetricBaseline(sample_count=3, window_seconds=900, ads_per_hour=200),
        policy=policy,
        last_calibration_at=now - timedelta(minutes=31),
        now=now,
    )

    assert blocked.should_calibrate is False
    assert "calibration_cooldown" in blocked.blockers
    assert ready.should_calibrate is True


def test_zero_ads_backoff_starts_after_eight_calibrations() -> None:
    now = datetime(2026, 7, 10, 12, tzinfo=UTC)
    policy = CalibrationPolicy(
        zero_ads_windows=1,
        zero_ads_calibration_cooldown_seconds=0,
        calibration_retry_cooldown_seconds=0,
    )
    attempts = [now - timedelta(minutes=30 * offset) for offset in range(1, 9)]

    decision = evaluate_calibration_need(
        _metrics(ads_total=0, target_ads=0),
        baseline=MetricBaseline(sample_count=3, window_seconds=900, ads_per_hour=200),
        policy=policy,
        calibration_attempt_timestamps=attempts,
        now=now,
    )

    assert decision.should_calibrate is False
    assert "zero_ads_calibration_backoff" in decision.blockers


def test_zero_ads_backoff_opens_a_new_burst_after_two_hours() -> None:
    now = datetime(2026, 7, 10, 15, 31, tzinfo=UTC)
    policy = CalibrationPolicy(
        zero_ads_windows=1,
        zero_ads_calibration_cooldown_seconds=0,
        calibration_retry_cooldown_seconds=0,
    )
    attempts = [
        datetime(2026, 7, 10, 10, tzinfo=UTC) + timedelta(minutes=30 * offset)
        for offset in range(8)
    ]

    decision = evaluate_calibration_need(
        _metrics(ads_total=0, target_ads=0),
        baseline=MetricBaseline(sample_count=3, window_seconds=900, ads_per_hour=200),
        policy=policy,
        calibration_attempt_timestamps=attempts,
        now=now,
    )

    assert decision.should_calibrate is True
    assert "zero_ads_calibration_backoff" not in decision.blockers


def test_nonzero_run_resets_zero_ads_calibration_burst() -> None:
    now = datetime(2026, 7, 10, 14, tzinfo=UTC)
    policy = CalibrationPolicy(
        zero_ads_windows=1,
        zero_ads_calibration_cooldown_seconds=0,
        calibration_retry_cooldown_seconds=0,
    )
    recovered = RunMetrics(
        **{
            **_metrics(ads_total=10, target_ads=2).to_dict(),
            "finished_at": "2026-07-10T13:30:00+00:00",
        }
    )
    attempts = [
        datetime(2026, 7, 10, 10, tzinfo=UTC) + timedelta(minutes=30 * offset)
        for offset in range(5)
    ]

    decision = evaluate_calibration_need(
        _metrics(ads_total=0, target_ads=0),
        history=[recovered],
        baseline=MetricBaseline(sample_count=3, window_seconds=900, ads_per_hour=200),
        policy=policy,
        calibration_attempt_timestamps=attempts,
        now=now,
    )

    assert decision.should_calibrate is True
    assert "zero_ads_calibration_backoff" not in decision.blockers


def test_two_absolute_low_ad_windows_calibrate_without_baseline() -> None:
    low = _metrics(ads_total=2, target_ads=0)

    decision = evaluate_calibration_need(
        low,
        history=[low],
    )

    assert decision.should_calibrate is True
    assert "absolute_low_ad_yield" in decision.reasons


def test_one_absolute_low_ad_window_is_only_observed() -> None:
    decision = evaluate_calibration_need(
        _metrics(ads_total=2, target_ads=0),
    )

    assert decision.should_calibrate is False
    assert decision.consecutive["absolute_low_ads"] == 1


def test_cooldown_does_not_make_healthy_collection_unhealthy() -> None:
    now = datetime(2026, 7, 10, tzinfo=UTC)
    current = _metrics(ads_total=50, target_ads=20)

    decision = evaluate_calibration_need(
        current,
        baseline=MetricBaseline(sample_count=3, window_seconds=900, ads_per_hour=200),
        last_calibration_at=now - timedelta(minutes=30),
        calibration_timestamps=[now - timedelta(minutes=30)],
        now=now,
    )

    assert decision.status == "healthy"
    assert decision.blockers == []


def test_missing_targets_block_only_when_calibration_is_needed() -> None:
    current = RunMetrics(
        **{
            **_metrics(ads_total=0, target_ads=0).to_dict(),
            "calibration_targets_available": 2,
        }
    )

    decision = evaluate_calibration_need(
        current,
        history=[_metrics(ads_total=0, target_ads=0)],
        baseline=MetricBaseline(sample_count=3, window_seconds=900, ads_per_hour=200),
    )

    assert decision.should_calibrate is False
    assert "zero_ads_repeated" in decision.reasons
    assert "not_enough_calibration_targets" in decision.blockers


def test_three_available_targets_allow_calibration() -> None:
    current = RunMetrics(
        **{
            **_metrics(ads_total=0, target_ads=0).to_dict(),
            "calibration_targets_available": 3,
        }
    )

    decision = evaluate_calibration_need(
        current,
        history=[_metrics(ads_total=0, target_ads=0)],
        baseline=MetricBaseline(sample_count=3, window_seconds=900, ads_per_hour=200),
    )

    assert decision.should_calibrate is True
    assert "not_enough_calibration_targets" not in decision.blockers


def test_small_drop_from_baseline_does_not_calibrate_or_watch() -> None:
    policy = CalibrationPolicy()
    baseline = MetricBaseline(
        sample_count=3, window_seconds=900, ads_per_hour=200, target_per_hour=80
    )
    previous = [_metrics(ads_total=41, target_ads=18)]
    current = _metrics(ads_total=40, target_ads=18)

    decision = evaluate_calibration_need(
        current,
        history=previous,
        baseline=baseline,
        policy=policy,
    )

    assert decision.should_calibrate is False
    assert decision.status == "healthy"
    assert decision.reasons == []


def test_drop_over_thirty_percent_calibrates_immediately() -> None:
    policy = CalibrationPolicy()
    baseline = MetricBaseline(
        sample_count=3, window_seconds=900, ads_per_hour=200, target_per_hour=80
    )
    previous = [_metrics(ads_total=30, target_ads=15)]
    current = _metrics(ads_total=29, target_ads=14)

    decision = evaluate_calibration_need(
        current,
        history=previous,
        baseline=baseline,
        policy=policy,
    )

    assert decision.should_calibrate is True
    assert decision.status == "calibrate"
    assert "ad_yield_30pct_drop" in decision.reasons


def test_three_sustained_soft_drop_windows_trigger_calibration() -> None:
    baseline = MetricBaseline(
        sample_count=3,
        window_seconds=900,
        ads_per_hour=200,
        ads_per_100_scrolls=16.67,
        target_per_hour=80,
    )
    low = _metrics(ads_total=30, target_ads=15)

    decision = evaluate_calibration_need(
        low,
        history=[low, low],
        baseline=baseline,
    )

    assert decision.should_calibrate is True
    assert "ad_yield_sustained_soft_drop" in decision.reasons
    assert decision.severity == "medium"


def test_small_sustained_drop_can_trigger_early_calibration() -> None:
    policy = CalibrationPolicy(
        watch_drop_ratio=0.95,
        soft_drop_calibration_windows=2,
    )
    baseline = MetricBaseline(
        sample_count=3,
        window_seconds=900,
        ads_per_hour=200,
        ads_per_100_scrolls=16.67,
        target_per_hour=80,
    )
    slightly_low = _metrics(ads_total=46, target_ads=19)

    decision = evaluate_calibration_need(
        slightly_low,
        history=[slightly_low],
        baseline=baseline,
        policy=policy,
    )

    assert decision.should_calibrate is True
    assert "ad_yield_sustained_soft_drop" in decision.reasons


def test_proactive_guard_calibrates_after_one_multi_signal_drop() -> None:
    policy = CalibrationPolicy(proactive_quality_drop_enabled=True)
    baseline = MetricBaseline(
        sample_count=1,
        trusted=True,
        window_seconds=900,
        target_source="relevance",
        target_sample_count=1,
        target_per_hour=96,
        target_per_100_scrolls=8,
        relevant_rate=0.96,
    )
    current = _metrics(
        ads_total=24,
        target_ads=20,
        target_source="relevance",
        relevance_known=True,
        relevant_ads=20,
        relevant_rate=20 / 24,
    )

    decision = evaluate_calibration_need(current, baseline=baseline, policy=policy)

    assert decision.should_calibrate is True
    assert "proactive_quality_drop" in decision.reasons
    assert (
        len([item for item in decision.observations if item.startswith("proactive_")])
        >= 2
    )


def test_proactive_guard_ignores_single_noisy_signal() -> None:
    policy = CalibrationPolicy(proactive_quality_drop_enabled=True)
    baseline = MetricBaseline(
        sample_count=1,
        trusted=True,
        window_seconds=900,
        target_source="relevance",
        target_sample_count=1,
        target_per_hour=96,
        target_per_100_scrolls=8,
        relevant_rate=1.0,
    )
    raw = _metrics(
        ads_total=24,
        target_ads=23,
        target_source="relevance",
        relevance_known=True,
        relevant_ads=23,
        relevant_rate=23 / 24,
    ).to_dict()
    raw.update(target_per_hour=96, target_per_100_scrolls=8)

    decision = evaluate_calibration_need(
        RunMetrics(**raw),
        baseline=baseline,
        policy=policy,
    )

    assert decision.should_calibrate is False
    assert "proactive_quality_drop" not in decision.reasons
    assert "proactive_relevance_rate_drop" in decision.observations


def test_thirty_percent_ad_yield_drop_triggers_after_one_window() -> None:
    baseline = MetricBaseline(
        sample_count=3,
        window_seconds=900,
        ads_per_hour=200,
        ads_per_100_scrolls=16.67,
    )
    current = _metrics(ads_total=34, target_ads=10)

    decision = evaluate_calibration_need(current, baseline=baseline)

    assert decision.should_calibrate is True
    assert "ad_yield_30pct_drop" in decision.reasons


def test_less_than_thirty_percent_drop_waits_for_second_window() -> None:
    baseline = MetricBaseline(
        sample_count=3,
        window_seconds=900,
        ads_per_hour=200,
        ads_per_100_scrolls=16.67,
    )
    current = _metrics(ads_total=36, target_ads=10)

    decision = evaluate_calibration_need(current, baseline=baseline)

    assert decision.should_calibrate is False
    assert "ad_yield_30pct_drop" not in decision.reasons
    assert "ads_per_hour_soft_drop" not in decision.observations


def test_soft_drop_calibration_uses_one_hour_cooldown() -> None:
    now = datetime(2026, 7, 10, 12, tzinfo=UTC)
    baseline = MetricBaseline(
        sample_count=3,
        window_seconds=900,
        ads_per_hour=200,
        ads_per_100_scrolls=16.67,
        target_per_hour=80,
    )
    low = _metrics(ads_total=30, target_ads=15)

    blocked = evaluate_calibration_need(
        low,
        history=[low, low],
        baseline=baseline,
        last_calibration_at=now - timedelta(minutes=45),
        now=now,
    )
    ready = evaluate_calibration_need(
        low,
        history=[low, low],
        baseline=baseline,
        last_calibration_at=now - timedelta(minutes=61),
        now=now,
    )

    assert blocked.should_calibrate is False
    assert "calibration_cooldown" in blocked.blockers
    assert ready.should_calibrate is True


def test_healthy_profile_gets_periodic_maintenance_after_six_hours() -> None:
    now = datetime(2026, 7, 10, 12, tzinfo=UTC)
    old = _metrics_at(
        ads_total=50,
        target_ads=20,
        finished_at=now - timedelta(hours=7),
    )
    recent = _metrics_at(
        ads_total=50,
        target_ads=20,
        finished_at=now - timedelta(minutes=30),
    )
    current = _metrics_at(
        ads_total=50,
        target_ads=20,
        finished_at=now,
    )

    decision = evaluate_calibration_need(
        current,
        history=[old, recent],
        baseline=MetricBaseline(
            sample_count=3,
            window_seconds=900,
            ads_per_hour=200,
        ),
        now=now,
    )

    assert decision.should_calibrate is True
    assert decision.reasons == ["periodic_account_maintenance"]
    assert decision.severity == "low"


def test_periodic_maintenance_waits_for_three_windows_and_interval() -> None:
    now = datetime(2026, 7, 10, 12, tzinfo=UTC)
    old = _metrics_at(
        ads_total=50,
        target_ads=20,
        finished_at=now - timedelta(hours=7),
    )
    current = _metrics_at(
        ads_total=50,
        target_ads=20,
        finished_at=now,
    )

    too_few = evaluate_calibration_need(
        current,
        history=[old],
        baseline=MetricBaseline(
            sample_count=3,
            window_seconds=900,
            ads_per_hour=200,
        ),
        now=now,
    )
    too_soon = evaluate_calibration_need(
        current,
        history=[old, current],
        baseline=MetricBaseline(
            sample_count=3,
            window_seconds=900,
            ads_per_hour=200,
        ),
        last_calibration_at=now - timedelta(hours=5),
        now=now,
    )

    assert too_few.should_calibrate is False
    assert too_soon.should_calibrate is False


def test_severe_drop_needs_mature_baseline_before_ratio_calibration() -> None:
    policy = CalibrationPolicy()
    immature_baseline = MetricBaseline(
        sample_count=1, window_seconds=900, ads_per_hour=200, target_per_hour=80
    )
    previous = [_metrics(ads_total=20, target_ads=10)]
    current = _metrics(ads_total=19, target_ads=9)

    decision = evaluate_calibration_need(
        current,
        history=previous,
        baseline=immature_baseline,
        policy=policy,
    )

    assert decision.should_calibrate is False
    assert decision.status == "watch"
    assert "baseline_learning" in decision.observations


def test_trusted_seed_can_trigger_after_two_severe_windows() -> None:
    baseline = MetricBaseline(
        sample_count=1,
        window_seconds=900,
        trusted=True,
        ads_per_hour=200,
        target_per_hour=80,
    )
    previous = [_metrics(ads_total=20, target_ads=10)]
    current = _metrics(ads_total=19, target_ads=9)

    decision = evaluate_calibration_need(
        current,
        history=previous,
        baseline=baseline,
    )

    assert decision.should_calibrate is True
    assert "ads_per_hour_below_baseline" in decision.reasons


def test_severe_drop_with_mature_baseline_triggers_calibration() -> None:
    policy = CalibrationPolicy()
    baseline = MetricBaseline(
        sample_count=3, window_seconds=900, ads_per_hour=200, target_per_hour=80
    )
    previous = [_metrics(ads_total=20, target_ads=10)]
    current = _metrics(ads_total=19, target_ads=9)

    decision = evaluate_calibration_need(
        current,
        history=previous,
        baseline=baseline,
        policy=policy,
    )

    assert decision.should_calibrate is True
    assert "ads_per_hour_below_baseline" in decision.reasons


def test_relevance_baseline_does_not_mix_resolved_landing_targets() -> None:
    resolved = _metrics(ads_total=40, target_ads=20)
    relevant = _metrics(
        ads_total=40,
        target_ads=30,
        target_source="relevance",
        relevance_known=True,
        relevant_ads=30,
        relevant_rate=0.75,
    )

    baseline = baseline_from_history([resolved, relevant])

    assert baseline.target_source == "relevance"
    assert baseline.target_sample_count == 1
    assert baseline.target_per_hour == relevant.target_per_hour
    assert baseline.relevant_rate == 0.75


def test_low_relevance_window_is_not_used_as_relevance_baseline() -> None:
    resolved = _metrics(ads_total=40, target_ads=20)
    low_relevance = _metrics(
        ads_total=10,
        target_ads=10,
        target_source="relevance",
        relevance_known=True,
        relevant_ads=10,
        relevant_rate=1.0,
    )

    baseline = baseline_from_history([resolved, low_relevance])

    assert baseline.sample_count == 2
    assert baseline.target_source == "resolved_landings"
    assert baseline.target_per_hour == resolved.target_per_hour
    assert baseline.relevant_rate is None


def test_baseline_does_not_mix_different_window_lengths() -> None:
    short = _metrics(ads_total=50, target_ads=10)
    long = RunMetrics(
        **{
            **_metrics(ads_total=80, target_ads=15).to_dict(),
            "run_dir": "/tmp/long",
            "elapsed_seconds": 1800,
            "ads_per_hour": 160,
        }
    )

    baseline = baseline_from_history([short, long])

    assert baseline.sample_count == 1
    assert baseline.window_seconds == 1800
    assert baseline.source_run_dirs == ["/tmp/long"]


def test_baseline_does_not_mix_visible_and_headless_runs() -> None:
    visible = RunMetrics(
        **{
            **_metrics(ads_total=50, target_ads=10).to_dict(),
            "run_dir": "/tmp/visible",
            "octo_headless": False,
        }
    )
    headless = RunMetrics(
        **{
            **_metrics(ads_total=45, target_ads=8).to_dict(),
            "run_dir": "/tmp/headless",
            "octo_headless": True,
        }
    )

    baseline = baseline_from_history([visible, headless])

    assert baseline.sample_count == 1
    assert baseline.octo_headless is True
    assert baseline.source_run_dirs == ["/tmp/headless"]


def test_visible_window_does_not_count_as_consecutive_with_headless() -> None:
    visible = RunMetrics(
        **{
            **_metrics(ads_total=0, target_ads=0).to_dict(),
            "octo_headless": False,
        }
    )
    headless = RunMetrics(
        **{
            **_metrics(ads_total=0, target_ads=0).to_dict(),
            "octo_headless": True,
        }
    )

    decision = evaluate_calibration_need(
        headless,
        history=[visible],
        baseline=MetricBaseline(
            sample_count=1,
            window_seconds=900,
            octo_headless=True,
            trusted=True,
            ads_per_hour=100,
        ),
    )

    assert decision.should_calibrate is False
    assert decision.consecutive["zero_ads"] == 1


def _metrics(
    *,
    ads_total: int,
    target_ads: int,
    target_source: str = "resolved_landings",
    geo_match: bool = True,
    relevance_known: bool = False,
    relevant_ads: int | None = None,
    relevant_rate: float | None = None,
    stop_reason: str | None = None,
) -> RunMetrics:
    return RunMetrics(
        run_dir="/tmp/run",
        profile_country="Spain",
        expected_country="Spain",
        return_code=0,
        stop_reason=stop_reason,
        elapsed_seconds=900,
        scrolls=300,
        ads_total=ads_total,
        target_ads=target_ads,
        target_source=target_source,
        geo_observed=True,
        geo_match=geo_match,
        relevance_known=relevance_known,
        relevance_classified_ads=ads_total if relevance_known else 0,
        relevance_coverage=1.0 if relevance_known else None,
        relevant_ads=relevant_ads,
        relevant_rate=relevant_rate,
        ads_per_hour=ads_total / 0.25,
        target_per_hour=target_ads / 0.25,
        ads_per_100_scrolls=ads_total / 300 * 100,
        target_per_100_scrolls=target_ads / 300 * 100,
    )


def _metrics_at(
    *,
    ads_total: int,
    target_ads: int,
    finished_at: datetime,
) -> RunMetrics:
    metrics = _metrics(ads_total=ads_total, target_ads=target_ads)
    return RunMetrics(
        **{
            **metrics.to_dict(),
            "run_dir": f"/tmp/run-{finished_at.timestamp()}",
            "finished_at": finished_at.isoformat(),
        }
    )

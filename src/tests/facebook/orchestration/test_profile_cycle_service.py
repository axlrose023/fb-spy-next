from __future__ import annotations

import pytest

from app.facebook.calibration import CalibrationDecision, CalibrationPolicy
from app.facebook.orchestration import CollectionPipelineState, ProfileCycleService
from app.facebook.profiles import Profile
from tests.facebook.orchestration.profile_cycle_support import (
    CycleHarness,
    EvaluationStub,
    StateWriterStub,
    cycle_request,
    evaluation,
    metrics,
)

pytestmark = pytest.mark.unit


def test_healthy_cycle_records_health_without_calibration() -> None:
    profile = Profile(octo_profile_uuid="profile", label="spain", quality_guard=True)
    run_metrics = metrics(relevant_ads=18)
    policy = CalibrationPolicy()
    decision = CalibrationDecision(
        status="healthy",
        should_calibrate=False,
        severity="none",
    )
    evaluator = EvaluationStub(evaluation(decision, recovery_count=1))
    writer = StateWriterStub()
    harness = CycleHarness()

    schedule = ProfileCycleService(evaluator, writer, harness.hooks()).run(
        cycle_request(profile, run_metrics, policy)
    )

    assert schedule is writer.schedule
    assert evaluator.calls == [("profile", run_metrics, policy, True)]
    assert harness.calls == [
        ("health", decision),
        (
            "log",
            "health=healthy ads=20 target=18 recovery=1/3 reasons=- blockers=-",
        ),
    ]
    assert writer.calls[0]["calibrations"] == []
    assert writer.calls[0]["infrastructure_retry_required"] is False


def test_recovery_cycle_rotates_targets_and_persists_every_pass() -> None:
    profile = Profile(
        octo_profile_uuid="profile",
        label="spain",
        failed_recovery_calibration_passes=3,
    )
    run_metrics = metrics(relevant_ads=1)
    previous = metrics(relevant_ads=5)
    policy = CalibrationPolicy(max_calibrations_per_24h=5)
    decision = CalibrationDecision(
        status="calibrate",
        should_calibrate=True,
        severity="high",
        reasons=["low_relevance"],
    )
    evaluator = EvaluationStub(
        evaluation(
            decision,
            history=(previous,),
            target_offset=7,
            recovery_count=2,
            recovery_active=True,
        )
    )
    writer = StateWriterStub()
    harness = CycleHarness()

    ProfileCycleService(evaluator, writer, harness.hooks()).run(
        cycle_request(profile, run_metrics, policy)
    )

    calibration_calls = [call for call in harness.calls if call[0] == "calibrate"]
    assert [(call[2], call[3]) for call in calibration_calls] == [
        (7, 10),
        (17, 10),
        (27, 10),
    ]
    records = writer.calls[0]["calibrations"]
    assert [record["pass_index"] for record in records] == [1, 2, 3]
    assert [record["planned_passes"] for record in records] == [3, 3, 3]
    assert (
        "log",
        "recovery did not improve; calibration pass 2/3 with 20 unused targets",
    ) in harness.calls
    assert writer.calls[0]["infrastructure_retry_required"] is False


def test_failed_pipeline_skips_calibration_and_requests_infrastructure_retry() -> None:
    profile = Profile(octo_profile_uuid="profile", label="spain")
    run_metrics = metrics()
    policy = CalibrationPolicy()
    decision = CalibrationDecision(
        status="calibrate",
        should_calibrate=True,
        severity="high",
    )
    evaluator = EvaluationStub(evaluation(decision))
    writer = StateWriterStub()
    harness = CycleHarness()

    ProfileCycleService(evaluator, writer, harness.hooks()).run(
        cycle_request(
            profile,
            run_metrics,
            policy,
            pipeline=CollectionPipelineState(relevance_code=5),
        )
    )

    assert not any(call[0] == "calibrate" for call in harness.calls)
    assert ("log", "calibration skipped: collection pipeline failed") in harness.calls
    assert writer.calls[0]["calibrations"] == []
    assert writer.calls[0]["infrastructure_retry_required"] is True


def test_stop_request_suppresses_calibration_without_marking_pipeline_failed() -> None:
    profile = Profile(octo_profile_uuid="profile")
    run_metrics = metrics()
    policy = CalibrationPolicy()
    decision = CalibrationDecision(
        status="calibrate",
        should_calibrate=True,
        severity="high",
    )
    evaluator = EvaluationStub(evaluation(decision))
    writer = StateWriterStub()
    harness = CycleHarness()
    harness.stopped = True

    ProfileCycleService(evaluator, writer, harness.hooks()).run(
        cycle_request(profile, run_metrics, policy)
    )

    assert not any(call[0] == "calibrate" for call in harness.calls)
    assert not any(
        call[0] == "log" and "calibration skipped" in call[1] for call in harness.calls
    )
    assert writer.calls[0]["calibrations"] == []
    assert writer.calls[0]["infrastructure_retry_required"] is False

from __future__ import annotations

import itertools

import pytest

from app.facebook.orchestration import (
    CalibrationTransition,
    CollectionPipelineState,
)

pytestmark = pytest.mark.unit

CODES = (None, 0, 1, 4)


def test_relevance_gate_matches_legacy_expression_exhaustively() -> None:
    for collect_code, safety_code in itertools.product((0, 1), CODES):
        state = CollectionPipelineState(
            collect_code=collect_code,
            interest_safety_code=safety_code,
        )
        for dry_run, stopped, enabled, ads_available in itertools.product(
            (False, True), repeat=4
        ):
            legacy = (
                collect_code == 0
                and safety_code in {None, 0}
                and not dry_run
                and not stopped
                and enabled
                and ads_available
            )
            assert (
                state.can_start_relevance(
                    dry_run=dry_run,
                    stop_requested=stopped,
                    relevance_enabled=enabled,
                    ads_available=ads_available,
                )
                is legacy
            )


def test_backend_import_gate_matches_legacy_expression_exhaustively() -> None:
    for collect_code, relevance_code in itertools.product((0, 1), CODES):
        state = CollectionPipelineState(
            collect_code=collect_code,
            relevance_code=relevance_code,
        )
        for import_enabled, safe_mode, dry_run, stopped in itertools.product(
            (False, True), repeat=4
        ):
            legacy = (
                collect_code == 0
                and import_enabled
                and not dry_run
                and not stopped
                and relevance_code in {None, 0}
                and (not safe_mode or relevance_code == 0)
            )
            assert (
                state.can_import_backend(
                    import_enabled=import_enabled,
                    interest_safe_collection=safe_mode,
                    dry_run=dry_run,
                    stop_requested=stopped,
                )
                is legacy
            )


def test_pipeline_failure_and_calibration_transition_match_legacy() -> None:
    for codes in itertools.product(CODES, repeat=6):
        state = CollectionPipelineState(
            interest_safety_code=codes[0],
            prefilter_code=codes[1],
            isolated_resolution_code=codes[2],
            gate_resolution_code=codes[3],
            enrichment_code=codes[4],
            relevance_code=codes[5],
        )
        legacy_failed = any(code not in {None, 0} for code in codes)
        assert state.post_collection_failed is legacy_failed
        for requested, stopped in itertools.product((False, True), repeat=2):
            expected = CalibrationTransition.NONE
            if requested and not stopped and not legacy_failed:
                expected = CalibrationTransition.RUN
            elif requested and legacy_failed:
                expected = CalibrationTransition.SKIP_PIPELINE_FAILED
            assert (
                state.calibration_transition(
                    calibration_requested=requested,
                    stop_requested=stopped,
                )
                is expected
            )


@pytest.mark.parametrize(
    ("isolated_code", "gate_code", "succeeded", "failure_code"),
    [
        (None, None, True, 0),
        (0, 0, True, 0),
        (4, None, False, 4),
        (4, 5, False, 5),
        (None, 5, False, 5),
    ],
)
def test_resolution_transition_preserves_gate_precedence(
    isolated_code: int | None,
    gate_code: int | None,
    succeeded: bool,
    failure_code: int | None,
) -> None:
    state = CollectionPipelineState(
        isolated_resolution_code=isolated_code,
        gate_resolution_code=gate_code,
    )

    assert state.resolution_succeeded is succeeded
    assert state.resolution_result_code == failure_code
    assert state.resolution_failure_code == (gate_code or isolated_code)


def test_disabled_relevance_gate_matches_legacy_expression() -> None:
    for collect_code in (0, 1):
        state = CollectionPipelineState(collect_code=collect_code)
        for safe_mode, dry_run, enabled in itertools.product((False, True), repeat=3):
            legacy = collect_code == 0 and safe_mode and not dry_run and not enabled
            assert (
                state.should_record_disabled_relevance(
                    interest_safe_collection=safe_mode,
                    dry_run=dry_run,
                    relevance_enabled=enabled,
                )
                is legacy
            )

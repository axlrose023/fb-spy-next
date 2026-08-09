from __future__ import annotations

import json
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from app.facebook.calibration import CalibrationPolicy, is_good_baseline_candidate
from app.facebook.runs import collect_run_metrics

from .. import OrchestrationStateStore, ProfileEvaluationService

Output = Callable[[str, bool], None]


@dataclass(frozen=True, slots=True)
class EvaluateCommandRequest:
    state_path: Path
    run_dir: Path
    profile_uuid: str
    expected_country: str | None
    return_code: int | None
    default_elapsed_seconds: float | None
    default_scrolls: int | None
    calibration_targets: int | None


@dataclass(frozen=True, slots=True)
class SeedBaselineCommandRequest:
    state_path: Path
    run_dir: Path
    profile_uuid: str
    label: str
    expected_country: str | None
    default_elapsed_seconds: float | None
    default_scrolls: int | None


@dataclass(frozen=True, slots=True)
class MaintenanceCommandHooks:
    state_store: Callable[[Path], OrchestrationStateStore]
    output: Output


def run_evaluate_command(
    request: EvaluateCommandRequest,
    hooks: MaintenanceCommandHooks,
) -> int:
    policy = CalibrationPolicy()
    metrics = collect_run_metrics(
        request.run_dir,
        expected_country=request.expected_country,
        return_code=request.return_code,
        default_elapsed_seconds=request.default_elapsed_seconds,
        default_scrolls=request.default_scrolls,
        calibration_targets_available=request.calibration_targets,
    )
    decision = (
        ProfileEvaluationService(hooks.state_store(request.state_path))
        .evaluate(
            request.profile_uuid,
            metrics,
            policy,
            load_recovery_context=False,
            exclude_run_dir=metrics.run_dir,
        )
        .decision
    )
    hooks.output(_json(decision.to_dict()), False)
    return 10 if decision.should_calibrate else 0


def run_seed_baseline_command(
    request: SeedBaselineCommandRequest,
    hooks: MaintenanceCommandHooks,
) -> int:
    policy = CalibrationPolicy()
    metrics = collect_run_metrics(
        request.run_dir,
        expected_country=request.expected_country,
        default_elapsed_seconds=request.default_elapsed_seconds,
        default_scrolls=request.default_scrolls,
    )
    if not is_good_baseline_candidate(metrics, policy):
        hooks.output(
            "Run is not a good baseline candidate. "
            "Use a complete, geo-matched run with enough ads and targets.",
            True,
        )
        hooks.output(_json(metrics.to_dict()), False)
        return 1
    baseline = hooks.state_store(request.state_path).seed_baseline(
        request.profile_uuid,
        metrics,
        label=request.label,
        expected_country=request.expected_country,
        policy=policy,
    )
    hooks.output(_json(baseline.to_dict()), False)
    return 0


def _json(payload: object) -> str:
    return json.dumps(payload, ensure_ascii=False, indent=2)

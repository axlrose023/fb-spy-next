from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from app.facebook.orchestration.commands import (
    CollectionCommandHooks,
    CollectionCommandRequest,
    run_collection_command,
)
from app.facebook.profiles import Profile

pytestmark = pytest.mark.unit


def test_collection_command_wires_full_safe_pipeline(tmp_path: Path) -> None:
    commands: list[tuple[list[str], str, float]] = []
    writes: list[tuple[str, Any]] = []
    profile = Profile(octo_profile_uuid="profile", label="canada")

    def run_command(command: list[str], log_path: Path, timeout: float) -> int:
        commands.append((command, log_path.name, timeout))
        return 0

    pipeline = run_collection_command(
        _request(tmp_path, profile),
        CollectionCommandHooks(
            run_command=run_command,
            collector_command=lambda *_args: ["collect"],
            classifier_command=lambda _run_dir, stage, source, include_video: [
                "classify",
                stage,
                source.name if source else "-",
                str(include_video),
            ],
            isolated_resolver_command=lambda *_args: ["resolve"],
            enricher_command=lambda _profile, _run_dir, source: [
                "enrich",
                source.name,
            ],
            backend_import_command=lambda _profile, source: [
                "import",
                source.name,
            ],
            stop_requested=lambda: False,
            relevance_enabled=lambda: True,
            artifact_exists=lambda _path: True,
            audit_interest_safety=lambda _path: [],
            write_json=lambda path, payload: writes.append((path.name, payload)),
            log=lambda _message: None,
        ),
    )

    assert pipeline.collect_code == 0
    assert pipeline.prefilter_code == 0
    assert pipeline.isolated_resolution_code == 0
    assert pipeline.gate_resolution_code == 0
    assert pipeline.enrichment_code == 0
    assert pipeline.relevance_code == 0
    assert commands == [
        (["collect"], "runner.log", 11),
        (["classify", "prefilter", "-", "False"], "prefilter.log", 12),
        (["resolve"], "isolated_resolution.log", 13),
        (
            ["classify", "resolve-holds", "ads.isolated.json", "False"],
            "gate_resolution.log",
            12,
        ),
        (["enrich", "ads.gated.json"], "enrichment.log", 14),
        (
            ["classify", "finalize", "ads.enriched.json", "True"],
            "relevance.log",
            12,
        ),
        (["import", "ads.relevant.json"], "backend_import.log", 15),
    ]
    assert writes == [
        (
            "interest_safety.json",
            {"status": "passed", "violations": []},
        )
    ]


def test_collection_command_records_disabled_safe_relevance(
    tmp_path: Path,
) -> None:
    commands: list[str] = []
    writes: list[tuple[str, Any]] = []
    logs: list[str] = []
    profile = Profile(octo_profile_uuid="profile", label="canada")

    def run_command(command: list[str], _path: Path, _timeout: float) -> int:
        commands.append(command[0])
        return 0

    pipeline = run_collection_command(
        _request(tmp_path, profile),
        CollectionCommandHooks(
            run_command=run_command,
            collector_command=lambda *_args: ["collect"],
            classifier_command=lambda *_args: ["classify"],
            isolated_resolver_command=lambda *_args: ["resolve"],
            enricher_command=lambda *_args: ["enrich"],
            backend_import_command=lambda *_args: ["import"],
            stop_requested=lambda: False,
            relevance_enabled=lambda: False,
            artifact_exists=lambda _path: True,
            audit_interest_safety=lambda _path: [],
            write_json=lambda path, payload: writes.append((path.name, payload)),
            log=logs.append,
        ),
    )

    assert pipeline.relevance_code is None
    assert commands == ["collect"]
    assert writes == [
        ("interest_safety.json", {"status": "passed", "violations": []}),
        (
            "relevance_summary.json",
            {
                "status": "disabled_in_interest_safe_collection",
                "total": 0,
            },
        ),
    ]
    assert logs == [
        "[canada] safe collection has no relevance classifier; "
        "active enrichment and backend import are disabled"
    ]


def _request(
    tmp_path: Path,
    profile: Profile,
) -> CollectionCommandRequest:
    return CollectionCommandRequest(
        profile=profile,
        collect_dir=tmp_path / "collect",
        dry_run=False,
        interest_safe_collection=True,
        isolated_hold_resolution=True,
        relevant_enrichment=True,
        import_backend=True,
        include_video=True,
        collector_timeout=11,
        relevance_timeout=12,
        isolated_resolution_timeout=13,
        enrichment_timeout=14,
        backend_import_timeout=15,
    )

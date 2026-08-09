from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any

from ..configuration import configured_relevance_service
from ..files import load_ads, write_json
from .service import EvidenceService


def run_resolve_holds(
    _args: Any,
    run_dir: Path,
    source_path: Path,
    config: Any,
) -> int:
    summary_path = run_dir / "gate_summary.json"
    if not source_path.exists():
        write_json(
            summary_path,
            {"status": "no_isolated_ads_file", "source": str(source_path)},
        )
        return 2
    raw_ads = load_ads(source_path)
    relevance = configured_relevance_service(config)
    if not relevance.enabled:
        write_json(summary_path, {"status": "disabled", "total": len(raw_ads)})
        return 2
    evidence = EvidenceService(
        relevance,
        concurrency=config.facebook.relevance_filter_concurrency,
    )
    gated = asyncio.run(evidence.resolve_held_ads(raw_ads, run_dir))
    errors = [item for item in gated if item.get("_gate_resolution_error")]
    write_json(run_dir / "ads.gated.json", gated)
    write_json(
        summary_path,
        {
            "status": "completed" if not errors else "partial",
            "total": len(gated),
            "allowed": _gate_count(gated, "allow"),
            "denied": _gate_count(gated, "deny"),
            "held": _gate_count(gated, "hold"),
            "isolated_classified": sum(
                isinstance(item.get("isolated_relevance"), dict) for item in gated
            ),
            "isolated_promoted": _isolated_count(gated, "allow"),
            "isolated_rejected": _isolated_count(gated, "deny"),
            "errors": len(errors),
        },
    )
    print(
        f"[relevance gate] total={len(gated)} "
        f"allowed={_gate_count(gated, 'allow')} "
        f"denied={_gate_count(gated, 'deny')} held={_gate_count(gated, 'hold')}",
        flush=True,
    )
    return 0 if not errors else 3


def _gate_count(rows: list[dict[str, Any]], gate: str) -> int:
    return sum(item.get("relevance_gate") == gate for item in rows)


def _isolated_count(rows: list[dict[str, Any]], gate: str) -> int:
    return sum(
        item.get("relevance_gate") == gate
        and item.get("relevance_gate_source") == "isolated_landing"
        for item in rows
    )

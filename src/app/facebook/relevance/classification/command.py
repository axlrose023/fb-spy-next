from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any

from ..configuration import configured_relevance_service
from ..evidence.service import EvidenceService, enrichment_was_active
from ..files import (
    classification_is_complete,
    is_not_relevant,
    is_relevant,
    load_ads,
    write_json,
)
from .batches import classify_ads


def run_standard(args: Any, run_dir: Path, source_path: Path, config: Any) -> int:
    summary_path = run_dir / "relevance_summary.json"
    if not source_path.exists():
        write_json(summary_path, {"status": "no_ads_file", "source": str(source_path)})
        return 2
    raw_ads = load_ads(source_path)
    classified_path = run_dir / "ads.classified.json"
    if not args.force and classification_is_complete(classified_path, len(raw_ads)):
        print(f"[relevance] cached ads={len(raw_ads)}", flush=True)
        return 0
    relevance = configured_relevance_service(config)
    if not relevance.enabled:
        return _disabled(summary_path, len(raw_ads))
    classified = asyncio.run(
        classify_ads(
            raw_ads,
            run_dir,
            relevance,
            concurrency=config.facebook.relevance_filter_concurrency,
            include_video=args.include_video,
        )
    )
    return _write_standard_results(run_dir, classified)


def run_prefilter(args: Any, run_dir: Path, source_path: Path, config: Any) -> int:
    summary_path = run_dir / "prefilter_summary.json"
    if not source_path.exists():
        write_json(summary_path, {"status": "no_ads_file", "source": str(source_path)})
        return 2
    raw_ads = load_ads(source_path)
    relevance = configured_relevance_service(config)
    if not relevance.enabled:
        return _disabled(summary_path, len(raw_ads))
    analyzed = asyncio.run(
        classify_ads(
            raw_ads,
            run_dir,
            relevance,
            concurrency=config.facebook.relevance_filter_concurrency,
            include_video=False,
            feed_only=True,
        )
    )
    decorated = [_decorate_prefilter(item) for item in analyzed]
    allowed = [item for item in decorated if item.get("relevance_gate") == "allow"]
    denied = [item for item in decorated if item.get("relevance_gate") == "deny"]
    held = [item for item in decorated if item.get("relevance_gate") == "hold"]
    errors = [item for item in held if item.get("prefilter_error")]
    write_json(run_dir / "ads.prefilter.json", decorated)
    write_json(run_dir / "ads.candidates.json", allowed)
    write_json(run_dir / "ads.prefilter_not_relevant.json", denied)
    write_json(
        summary_path,
        {
            "status": "completed" if not errors else "partial",
            "total": len(decorated),
            "allowed": len(allowed),
            "denied": len(denied),
            "held": len(held),
            "errors": len(errors),
            "active_actions_allowed": len(allowed),
            "active_actions_blocked": len(denied) + len(held),
        },
    )
    print(
        f"[prefilter] total={len(decorated)} allowed={len(allowed)} "
        f"denied={len(denied)} held={len(held)}",
        flush=True,
    )
    return 0 if not errors else 3


def run_finalize(args: Any, run_dir: Path, source_path: Path, config: Any) -> int:
    summary_path = run_dir / "relevance_summary.json"
    if not source_path.exists():
        write_json(
            summary_path,
            {"status": "no_enriched_ads_file", "source": str(source_path)},
        )
        return 2
    raw_ads = load_ads(source_path)
    relevance = configured_relevance_service(config)
    if not relevance.enabled:
        return _disabled(summary_path, len(raw_ads))
    evidence = EvidenceService(
        relevance,
        concurrency=config.facebook.relevance_filter_concurrency,
    )
    finalized = asyncio.run(
        evidence.finalize_ads(
            raw_ads,
            run_dir,
            include_video=args.include_video,
        )
    )
    return _write_final_results(run_dir, finalized)


def _decorate_prefilter(item: dict[str, Any]) -> dict[str, Any]:
    result = dict(item)
    relevance = result.pop("relevance", None)
    source = result.pop("relevance_source", None)
    error = result.pop("_relevance_error", None)
    if isinstance(relevance, dict):
        result["prefilter_relevance"] = relevance
        result["prefilter_relevance_source"] = source
        decision = relevance.get("result")
        result["relevance_gate"] = (
            "allow" if decision == "relevant" else "deny" if decision == "not_relevant" else "hold"
        )
    else:
        result["relevance_gate"] = "hold"
        result["prefilter_error"] = error or "classification did not return a result"
    return result


def _disabled(summary_path: Path, total: int) -> int:
    write_json(summary_path, {"status": "disabled", "total": total})
    print("[relevance] filter disabled or Gemini API key is missing", flush=True)
    return 2


def _write_standard_results(run_dir: Path, rows: list[dict[str, Any]]) -> int:
    relevant = [item for item in rows if is_relevant(item)]
    rejected = [item for item in rows if is_not_relevant(item)]
    failed = [item for item in rows if item.get("_relevance_error")]
    write_json(run_dir / "ads.classified.json", rows)
    write_json(run_dir / "ads.relevant.json", relevant)
    write_json(run_dir / "ads.not_relevant.json", rejected)
    _write_relevance_summary(run_dir, rows, relevant, rejected, failed)
    status = "completed" if not failed else "partial"
    print(
        f"[relevance] status={status} total={len(rows)} "
        f"relevant={len(relevant)} failed={len(failed)}",
        flush=True,
    )
    return 0 if not failed else 3


def _write_final_results(run_dir: Path, rows: list[dict[str, Any]]) -> int:
    relevant = [item for item in rows if is_relevant(item)]
    rejected = [item for item in rows if is_not_relevant(item)]
    failed = [item for item in rows if item.get("_relevance_error")]
    false_positives = [
        item
        for item in rows
        if item.get("relevance_gate") == "allow"
        and enrichment_was_active(item)
        and is_not_relevant(item)
    ]
    write_json(run_dir / "ads.classified.json", rows)
    write_json(run_dir / "ads.relevant.json", relevant)
    write_json(run_dir / "ads.not_relevant.json", rejected)
    _write_relevance_summary(
        run_dir,
        rows,
        relevant,
        rejected,
        failed,
        active_false_positives=len(false_positives),
    )
    print(
        f"[relevance finalize] total={len(rows)} relevant={len(relevant)} "
        f"failed={len(failed)} active_false_positives={len(false_positives)}",
        flush=True,
    )
    return 0 if not failed else 3


def _write_relevance_summary(
    run_dir: Path,
    rows: list[dict[str, Any]],
    relevant: list[dict[str, Any]],
    rejected: list[dict[str, Any]],
    failed: list[dict[str, Any]],
    *,
    active_false_positives: int | None = None,
) -> None:
    classified = len(rows) - len(failed)
    summary: dict[str, Any] = {
        "status": "completed" if not failed else "partial",
        "total": len(rows),
        "classified": classified,
        "relevant": len(relevant),
        "not_relevant": len(rejected),
        "failed": len(failed),
        "relevant_rate": len(relevant) / classified if classified else None,
    }
    if active_false_positives is not None:
        summary.update(
            {
                "prefilter_allowed": sum(
                    item.get("relevance_gate") == "allow" for item in rows
                ),
                "active_enrichments": sum(enrichment_was_active(item) for item in rows),
                "final_rejected_after_active_enrichment": active_false_positives,
            }
        )
    write_json(run_dir / "relevance_summary.json", summary)

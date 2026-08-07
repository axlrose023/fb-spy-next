"""Classify one collector run without importing it into the backend database."""

from __future__ import annotations

import argparse
import asyncio
import json
from pathlib import Path
from typing import Any

from app.services.facebook.relevance import FacebookAdRelevanceFilter
from app.settings import get_config


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-dir", type=Path, required=True)
    parser.add_argument(
        "--stage",
        choices=("standard", "prefilter", "resolve-holds", "finalize"),
        default="standard",
    )
    parser.add_argument("--source", type=Path, default=None)
    parser.add_argument("--force", action="store_true")
    parser.add_argument("--include-video", action="store_true")
    args = parser.parse_args()

    run_dir = args.run_dir.expanduser().resolve()
    source_path = _source_path(run_dir, args.stage, args.source)
    if args.stage == "prefilter":
        return _run_prefilter(args, run_dir, source_path)
    if args.stage == "resolve-holds":
        return _run_resolve_holds(args, run_dir, source_path)
    if args.stage == "finalize":
        return _run_finalize(args, run_dir, source_path)

    classified_path = run_dir / "ads.classified.json"
    if not source_path.exists():
        _write_json(run_dir / "relevance_summary.json", {
            "status": "no_ads_file",
            "source": str(source_path),
        })
        return 2

    raw_ads = _load_ads(source_path)
    if not args.force and _classification_is_complete(classified_path, len(raw_ads)):
        print(f"[relevance] cached ads={len(raw_ads)}", flush=True)
        return 0

    relevance_filter = FacebookAdRelevanceFilter.from_config(get_config())
    if not relevance_filter.enabled:
        _write_json(run_dir / "relevance_summary.json", {
            "status": "disabled",
            "total": len(raw_ads),
        })
        print("[relevance] filter disabled or Gemini API key is missing", flush=True)
        return 2

    classified = asyncio.run(_classify(
        raw_ads,
        run_dir,
        relevance_filter,
        include_video=args.include_video,
    ))
    relevant = [item for item in classified if _is_relevant(item)]
    not_relevant = [item for item in classified if _is_not_relevant(item)]
    failed = [item for item in classified if item.get("_relevance_error")]

    _write_json(classified_path, classified)
    _write_json(run_dir / "ads.relevant.json", relevant)
    _write_json(run_dir / "ads.not_relevant.json", not_relevant)
    status = "completed" if not failed else "partial"
    _write_json(run_dir / "relevance_summary.json", {
        "status": status,
        "total": len(raw_ads),
        "classified": len(raw_ads) - len(failed),
        "relevant": len(relevant),
        "not_relevant": len(not_relevant),
        "failed": len(failed),
        "relevant_rate": (
            len(relevant) / (len(raw_ads) - len(failed))
            if len(raw_ads) > len(failed)
            else None
        ),
    })
    print(
        f"[relevance] status={status} total={len(raw_ads)} "
        f"relevant={len(relevant)} failed={len(failed)}",
        flush=True,
    )
    return 0 if not failed else 3


def _run_prefilter(args, run_dir: Path, source_path: Path) -> int:
    summary_path = run_dir / "prefilter_summary.json"
    if not source_path.exists():
        _write_json(summary_path, {
            "status": "no_ads_file",
            "source": str(source_path),
        })
        return 2

    raw_ads = _load_ads(source_path)
    relevance_filter = FacebookAdRelevanceFilter.from_config(get_config())
    if not relevance_filter.enabled:
        _write_json(summary_path, {
            "status": "disabled",
            "total": len(raw_ads),
        })
        return 2

    analyzed = asyncio.run(_classify(
        raw_ads,
        run_dir,
        relevance_filter,
        include_video=False,
        feed_only=True,
    ))
    decorated: list[dict[str, Any]] = []
    for item in analyzed:
        result = dict(item)
        relevance = result.pop("relevance", None)
        relevance_source = result.pop("relevance_source", None)
        error = result.pop("_relevance_error", None)
        if isinstance(relevance, dict):
            result["prefilter_relevance"] = relevance
            result["prefilter_relevance_source"] = relevance_source
            relevance_result = relevance.get("result")
            result["relevance_gate"] = (
                "allow"
                if relevance_result == "relevant"
                else "deny"
                if relevance_result == "not_relevant"
                else "hold"
            )
        else:
            result["relevance_gate"] = "hold"
            result["prefilter_error"] = error or "classification did not return a result"
        decorated.append(result)

    allowed = [item for item in decorated if item.get("relevance_gate") == "allow"]
    denied = [item for item in decorated if item.get("relevance_gate") == "deny"]
    held = [item for item in decorated if item.get("relevance_gate") == "hold"]
    errors = [item for item in held if item.get("prefilter_error")]
    _write_json(run_dir / "ads.prefilter.json", decorated)
    _write_json(run_dir / "ads.candidates.json", allowed)
    _write_json(run_dir / "ads.prefilter_not_relevant.json", denied)
    _write_json(summary_path, {
        "status": "completed" if not errors else "partial",
        "total": len(decorated),
        "allowed": len(allowed),
        "denied": len(denied),
        "held": len(held),
        "errors": len(errors),
        "active_actions_allowed": len(allowed),
        "active_actions_blocked": len(denied) + len(held),
    })
    print(
        f"[prefilter] total={len(decorated)} allowed={len(allowed)} "
        f"denied={len(denied)} held={len(held)}",
        flush=True,
    )
    return 0 if not errors else 3


def _run_finalize(args, run_dir: Path, source_path: Path) -> int:
    if not source_path.exists():
        _write_json(run_dir / "relevance_summary.json", {
            "status": "no_enriched_ads_file",
            "source": str(source_path),
        })
        return 2

    raw_ads = _load_ads(source_path)
    relevance_filter = FacebookAdRelevanceFilter.from_config(get_config())
    if not relevance_filter.enabled:
        _write_json(run_dir / "relevance_summary.json", {
            "status": "disabled",
            "total": len(raw_ads),
        })
        return 2

    finalized = asyncio.run(_finalize_ads(
        raw_ads,
        run_dir,
        relevance_filter,
        include_video=args.include_video,
    ))
    relevant = [item for item in finalized if _is_relevant(item)]
    not_relevant = [item for item in finalized if _is_not_relevant(item)]
    failed = [item for item in finalized if item.get("_relevance_error")]
    false_positive_actions = [
        item
        for item in finalized
        if item.get("relevance_gate") == "allow"
        and _enrichment_was_active(item)
        and _is_not_relevant(item)
    ]

    _write_json(run_dir / "ads.classified.json", finalized)
    _write_json(run_dir / "ads.relevant.json", relevant)
    _write_json(run_dir / "ads.not_relevant.json", not_relevant)
    _write_json(run_dir / "relevance_summary.json", {
        "status": "completed" if not failed else "partial",
        "total": len(finalized),
        "classified": len(finalized) - len(failed),
        "relevant": len(relevant),
        "not_relevant": len(not_relevant),
        "failed": len(failed),
        "relevant_rate": (
            len(relevant) / (len(finalized) - len(failed))
            if len(finalized) > len(failed)
            else None
        ),
        "prefilter_allowed": sum(
            item.get("relevance_gate") == "allow" for item in finalized
        ),
        "active_enrichments": sum(_enrichment_was_active(item) for item in finalized),
        "final_rejected_after_active_enrichment": len(false_positive_actions),
    })
    print(
        f"[relevance finalize] total={len(finalized)} relevant={len(relevant)} "
        f"failed={len(failed)} active_false_positives={len(false_positive_actions)}",
        flush=True,
    )
    return 0 if not failed else 3


def _run_resolve_holds(args, run_dir: Path, source_path: Path) -> int:
    summary_path = run_dir / "gate_summary.json"
    if not source_path.exists():
        _write_json(summary_path, {
            "status": "no_isolated_ads_file",
            "source": str(source_path),
        })
        return 2

    raw_ads = _load_ads(source_path)
    relevance_filter = FacebookAdRelevanceFilter.from_config(get_config())
    if not relevance_filter.enabled:
        _write_json(summary_path, {
            "status": "disabled",
            "total": len(raw_ads),
        })
        return 2

    gated = asyncio.run(_resolve_held_ads(
        raw_ads,
        run_dir,
        relevance_filter,
    ))
    errors = [item for item in gated if item.get("_gate_resolution_error")]
    _write_json(run_dir / "ads.gated.json", gated)
    _write_json(summary_path, {
        "status": "completed" if not errors else "partial",
        "total": len(gated),
        "allowed": sum(item.get("relevance_gate") == "allow" for item in gated),
        "denied": sum(item.get("relevance_gate") == "deny" for item in gated),
        "held": sum(item.get("relevance_gate") == "hold" for item in gated),
        "isolated_classified": sum(
            isinstance(item.get("isolated_relevance"), dict)
            for item in gated
        ),
        "isolated_promoted": sum(
            item.get("relevance_gate") == "allow"
            and item.get("relevance_gate_source") == "isolated_landing"
            for item in gated
        ),
        "isolated_rejected": sum(
            item.get("relevance_gate") == "deny"
            and item.get("relevance_gate_source") == "isolated_landing"
            for item in gated
        ),
        "errors": len(errors),
    })
    print(
        f"[relevance gate] total={len(gated)} "
        f"allowed={sum(item.get('relevance_gate') == 'allow' for item in gated)} "
        f"denied={sum(item.get('relevance_gate') == 'deny' for item in gated)} "
        f"held={sum(item.get('relevance_gate') == 'hold' for item in gated)}",
        flush=True,
    )
    return 0 if not errors else 3


async def _classify(
    raw_ads: list[dict[str, Any]],
    run_dir: Path,
    relevance_filter: FacebookAdRelevanceFilter,
    *,
    include_video: bool,
    feed_only: bool = False,
) -> list[dict[str, Any]]:
    concurrency = max(1, get_config().facebook.relevance_filter_concurrency)
    semaphore = asyncio.Semaphore(concurrency)

    async def classify_one(raw: dict[str, Any]) -> dict[str, Any]:
        decorated = dict(raw)
        try:
            analysis_input = _analysis_input(
                raw,
                include_video=include_video,
                feed_only=feed_only,
            )
            async with semaphore:
                result = await relevance_filter.analyze_raw_ad(
                    analysis_input,
                    run_dir,
                    prefilter=feed_only,
                )
            decorated["relevance"] = result.summary
            decorated["relevance_source"] = result.source
        except Exception as exc:
            decorated["_relevance_error"] = repr(exc)
        return decorated

    return list(await asyncio.gather(*(classify_one(raw) for raw in raw_ads)))


async def _finalize_ads(
    raw_ads: list[dict[str, Any]],
    run_dir: Path,
    relevance_filter: FacebookAdRelevanceFilter,
    *,
    include_video: bool,
) -> list[dict[str, Any]]:
    concurrency = max(1, get_config().facebook.relevance_filter_concurrency)
    semaphore = asyncio.Semaphore(concurrency)

    async def finalize_one(raw: dict[str, Any]) -> dict[str, Any]:
        decorated = dict(raw)
        gate = str(raw.get("relevance_gate") or "hold")
        prefilter = raw.get("prefilter_relevance")
        isolated = raw.get("isolated_relevance")
        if gate == "deny":
            if isinstance(isolated, dict):
                decorated["relevance"] = dict(isolated)
                decorated["relevance_source"] = "isolated_landing"
            elif isinstance(prefilter, dict):
                decorated["relevance"] = dict(prefilter)
                decorated["relevance_source"] = "feed_prefilter"
            else:
                decorated["_relevance_error"] = "missing deny result"
            return decorated
        if gate == "hold":
            if raw.get("prefilter_error"):
                decorated["_relevance_error"] = str(raw["prefilter_error"])
            else:
                decorated["relevance"] = {
                    "result": "not_relevant",
                    "reason": (
                        "Held by the passive relevance gate; no authenticated "
                        "Facebook profile action was allowed."
                    ),
                }
                decorated["relevance_source"] = "feed_prefilter_hold"
            return decorated
        if not _enrichment_was_active(raw):
            if isinstance(isolated, dict):
                decorated["relevance"] = dict(isolated)
                decorated["relevance_source"] = (
                    "isolated_landing_no_profile_enrichment"
                )
            elif (
                isinstance(prefilter, dict)
                and prefilter.get("result") in {"relevant", "not_relevant"}
            ):
                decorated["relevance"] = dict(prefilter)
                decorated["relevance_source"] = "feed_prefilter_no_active_enrichment"
            else:
                decorated["_relevance_error"] = "missing binary gate result"
            return decorated
        try:
            async with semaphore:
                result = await relevance_filter.analyze_raw_ad(
                    _analysis_input(
                        raw,
                        include_video=include_video,
                        feed_only=False,
                    ),
                    run_dir,
                )
            decorated["relevance"] = result.summary
            decorated["relevance_source"] = result.source
        except Exception as exc:
            decorated["_relevance_error"] = repr(exc)
        return decorated

    return list(await asyncio.gather(*(finalize_one(raw) for raw in raw_ads)))


async def _resolve_held_ads(
    raw_ads: list[dict[str, Any]],
    run_dir: Path,
    relevance_filter: FacebookAdRelevanceFilter,
) -> list[dict[str, Any]]:
    concurrency = max(1, get_config().facebook.relevance_filter_concurrency)
    semaphore = asyncio.Semaphore(concurrency)

    async def resolve_one(raw: dict[str, Any]) -> dict[str, Any]:
        decorated = dict(raw)
        if raw.get("relevance_gate") != "hold":
            return decorated
        if not _isolated_resolution_available(raw):
            decorated["relevance_gate_source"] = "feed_prefilter_unresolved"
            return decorated
        try:
            async with semaphore:
                result = await relevance_filter.analyze_raw_ad(
                    _analysis_input(
                        raw,
                        include_video=False,
                        feed_only=False,
                    ),
                    run_dir,
                )
            decorated["isolated_relevance"] = result.summary
            decorated["isolated_relevance_source"] = result.source
            decorated["relevance_gate"] = (
                "allow"
                if result.summary.get("result") == "relevant"
                else "deny"
            )
            decorated["relevance_gate_source"] = "isolated_landing"
        except Exception as exc:
            decorated["_gate_resolution_error"] = repr(exc)
            decorated["relevance_gate"] = "hold"
            decorated["relevance_gate_source"] = "isolated_classification_error"
        return decorated

    return list(await asyncio.gather(*(resolve_one(raw) for raw in raw_ads)))


def _analysis_input(
    raw: dict[str, Any],
    *,
    include_video: bool,
    feed_only: bool,
) -> dict[str, Any]:
    excluded = set()
    if not include_video:
        excluded.update({"video", "video_path"})
    if feed_only:
        excluded.update({
            "landing_full",
            "landing_clean",
            "landing_screenshot",
            "landing_archive",
            "utm",
        })
    return {key: value for key, value in raw.items() if key not in excluded}


def _enrichment_was_active(raw: dict[str, Any]) -> bool:
    enrichment = raw.get("enrichment")
    return (
        isinstance(enrichment, dict)
        and bool(enrichment.get("active_actions_started"))
    )


def _isolated_resolution_available(raw: dict[str, Any]) -> bool:
    resolution = raw.get("isolated_resolution")
    return bool(
        isinstance(resolution, dict)
        and resolution.get("status") in {"completed", "reused_isolated_result"}
        and resolution.get("landing_resolved")
        and raw.get("landing_full")
        and raw.get("landing_screenshot")
        and resolution.get("cookie_isolated") is True
        and resolution.get("authenticated_profile_context") is False
        and not resolution.get("active_profile_actions_started")
    )


def _source_path(run_dir: Path, stage: str, source: Path | None) -> Path:
    if source is not None:
        return source.expanduser().resolve()
    if stage == "finalize":
        return run_dir / "ads.enriched.json"
    if stage == "resolve-holds":
        return run_dir / "ads.isolated.json"
    return run_dir / "ads.json"


def _classification_is_complete(path: Path, expected_count: int) -> bool:
    if not path.exists():
        return False
    try:
        ads = _load_ads(path)
    except (OSError, ValueError, json.JSONDecodeError):
        return False
    return len(ads) == expected_count and all(
        isinstance(ad.get("relevance"), dict)
        and ad["relevance"].get("result") in {"relevant", "not_relevant"}
        for ad in ads
    )


def _load_ads(path: Path) -> list[dict[str, Any]]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, list):
        raise ValueError(f"Expected a JSON list: {path}")
    return [item for item in payload if isinstance(item, dict)]


def _is_relevant(raw: dict[str, Any]) -> bool:
    relevance = raw.get("relevance")
    return isinstance(relevance, dict) and relevance.get("result") == "relevant"


def _is_not_relevant(raw: dict[str, Any]) -> bool:
    relevance = raw.get("relevance")
    return isinstance(relevance, dict) and relevance.get("result") == "not_relevant"


def _write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, default=str),
        encoding="utf-8",
    )
    tmp.replace(path)


if __name__ == "__main__":
    raise SystemExit(main())

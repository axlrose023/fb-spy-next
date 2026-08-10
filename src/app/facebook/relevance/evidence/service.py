from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any

from ..classification.input import analysis_input
from ..contracts import RelevanceAnalyzer


class EvidenceService:
    """Resolve held evidence and finalize relevance without bypassing the gate."""

    def __init__(
        self,
        relevance: RelevanceAnalyzer,
        *,
        concurrency: int = 3,
    ) -> None:
        self._relevance = relevance
        self._concurrency = max(1, concurrency)

    async def resolve_held_ads(
        self,
        raw_ads: list[dict[str, Any]],
        run_dir: Path,
    ) -> list[dict[str, Any]]:
        semaphore = asyncio.Semaphore(self._concurrency)

        async def resolve_one(raw: dict[str, Any]) -> dict[str, Any]:
            decorated = dict(raw)
            if raw.get("relevance_gate") != "hold":
                return decorated
            if not isolated_resolution_available(raw):
                decorated["relevance_gate_source"] = "feed_prefilter_unresolved"
                return decorated
            try:
                async with semaphore:
                    result = await self._relevance.analyze_raw_ad(
                        analysis_input(raw, include_video=False, feed_only=False),
                        run_dir,
                    )
                decorated["isolated_relevance"] = result.summary
                decorated["isolated_relevance_source"] = result.source
                decorated["relevance_gate"] = (
                    "allow" if result.summary.get("result") == "relevant" else "deny"
                )
                decorated["relevance_gate_source"] = "isolated_landing"
            except Exception as exc:
                decorated["_gate_resolution_error"] = repr(exc)
                decorated["relevance_gate"] = "hold"
                decorated["relevance_gate_source"] = "isolated_classification_error"
            return decorated

        return list(await asyncio.gather(*(resolve_one(raw) for raw in raw_ads)))

    async def finalize_ads(
        self,
        raw_ads: list[dict[str, Any]],
        run_dir: Path,
        *,
        include_video: bool,
    ) -> list[dict[str, Any]]:
        semaphore = asyncio.Semaphore(self._concurrency)

        async def finalize_one(raw: dict[str, Any]) -> dict[str, Any]:
            decorated = _settled_gate_result(raw)
            if decorated is not None:
                return decorated
            result = dict(raw)
            try:
                async with semaphore:
                    analysis = await self._relevance.analyze_raw_ad(
                        analysis_input(
                            raw,
                            include_video=include_video,
                            feed_only=False,
                        ),
                        run_dir,
                    )
                result["relevance"] = analysis.summary
                result["relevance_source"] = analysis.source
            except Exception as exc:
                result["_relevance_error"] = repr(exc)
            return result

        return list(await asyncio.gather(*(finalize_one(raw) for raw in raw_ads)))


def enrichment_was_active(raw: dict[str, Any]) -> bool:
    enrichment = raw.get("enrichment")
    return isinstance(enrichment, dict) and bool(
        enrichment.get("active_actions_started")
    )


def isolated_resolution_available(raw: dict[str, Any]) -> bool:
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


def _settled_gate_result(raw: dict[str, Any]) -> dict[str, Any] | None:
    gate = str(raw.get("relevance_gate") or "hold")
    prefilter = raw.get("prefilter_relevance")
    isolated = raw.get("isolated_relevance")
    result = dict(raw)
    if gate == "deny":
        if isinstance(isolated, dict):
            result["relevance"] = dict(isolated)
            result["relevance_source"] = "isolated_landing"
        elif isinstance(prefilter, dict):
            result["relevance"] = dict(prefilter)
            result["relevance_source"] = "feed_prefilter"
        else:
            result["_relevance_error"] = "missing deny result"
        return result
    if gate == "hold":
        if raw.get("prefilter_error"):
            result["_relevance_error"] = str(raw["prefilter_error"])
        else:
            result["relevance"] = {
                "result": "not_relevant",
                "reason": (
                    "Held by the passive relevance gate; no authenticated "
                    "Facebook profile action was allowed."
                ),
            }
            result["relevance_source"] = "feed_prefilter_hold"
        return result
    if enrichment_was_active(raw):
        return None
    if isinstance(isolated, dict):
        result["relevance"] = dict(isolated)
        result["relevance_source"] = "isolated_landing_no_profile_enrichment"
    elif isinstance(prefilter, dict) and prefilter.get("result") in {
        "relevant",
        "not_relevant",
    }:
        result["relevance"] = dict(prefilter)
        result["relevance_source"] = "feed_prefilter_no_active_enrichment"
    else:
        result["_relevance_error"] = "missing binary gate result"
    return result

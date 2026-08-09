from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from .contracts import RelevantAdExecutor
from .exceptions import RelevanceGateDenied
from .models import EnrichmentResult, RelevantAd


class EnrichmentService:
    def __init__(self, *, clock: Callable[[], str] | None = None) -> None:
        self._clock = clock or _utc_now

    def prepare(self, rows: list[dict[str, Any]]) -> list[int]:
        candidates: list[int] = []
        for index, row in enumerate(rows):
            if row.get("relevance_gate") == "allow":
                candidates.append(index)
            else:
                row["enrichment"] = blocked_result()
        return candidates

    def enrich_one(
        self,
        executor: RelevantAdExecutor,
        context: Any,
        raw: dict[str, Any],
        *,
        sequence: int,
        run_dir: Path,
    ) -> EnrichmentResult:
        candidate = RelevantAd.from_raw(raw)
        return executor.enrich(
            context,
            candidate,
            sequence=sequence,
            run_dir=run_dir,
        )

    def target_key(self, raw: dict[str, Any]) -> str:
        return RelevantAd.from_raw(raw).target_key

    def summary(
        self,
        rows: list[dict[str, Any]],
        *,
        status: str,
    ) -> dict[str, Any]:
        enrichments = [
            row["enrichment"] for row in rows if isinstance(row.get("enrichment"), dict)
        ]
        active_on_blocked = sum(
            row.get("relevance_gate") != "allow"
            and isinstance(row.get("enrichment"), dict)
            and bool(row["enrichment"].get("active_actions_started"))
            for row in rows
        )
        return {
            "status": status,
            "finished_at": self._clock(),
            "total": len(rows),
            "allowed": sum(row.get("relevance_gate") == "allow" for row in rows),
            "blocked": sum(row.get("relevance_gate") != "allow" for row in rows),
            "active_candidates": _count(enrichments, "active_actions_started"),
            "landing_click_attempts": _count(enrichments, "cta_click_attempted"),
            "landing_resolved": _count(enrichments, "landing_resolved"),
            "video_attempts": _count(enrichments, "video_attempted"),
            "videos_recorded": _count(enrichments, "video_recorded"),
            "post_url_recovery_attempts": sum(
                isinstance(item.get("post_url_recovery"), dict) for item in enrichments
            ),
            "post_urls_recovered": sum(
                isinstance(item.get("post_url_recovery"), dict)
                and item["post_url_recovery"].get("status") == "recovered"
                for item in enrichments
            ),
            "active_actions_on_blocked_ads": active_on_blocked,
        }


def blocked_result() -> dict[str, Any]:
    return {
        "status": "blocked_by_relevance_gate",
        "active_actions_started": False,
    }


def denied_enrichment(raw: dict[str, Any]) -> EnrichmentResult:
    if raw.get("relevance_gate") == "allow":
        raise RelevanceGateDenied("Allowed ads must be handled by the executor")
    details = blocked_result()
    enriched = dict(raw)
    enriched["enrichment"] = details
    return EnrichmentResult(enriched, details)


def _count(rows: list[dict[str, Any]], key: str) -> int:
    return sum(bool(row.get(key)) for row in rows)


def _utc_now() -> str:
    return datetime.now(UTC).isoformat()

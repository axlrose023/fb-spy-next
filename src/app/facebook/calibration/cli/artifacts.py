from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import Any

from ..adapters.persistence.artifacts import append_event, write_json, write_targets
from ..adapters.persistence.target_health import record_facebook_post_target_result
from ..planning import CalibrationTarget


class CalibrationArtifacts:
    def __init__(
        self,
        run_dir: Path,
        *,
        target_health_path: Path | None,
        utc_now: Callable[[], str],
    ) -> None:
        self.run_dir = run_dir
        self.events_path = run_dir / "events.jsonl"
        self.results_path = run_dir / "results.json"
        self.summary_path = run_dir / "summary.json"
        self.target_health_path = target_health_path
        self.utc_now = utc_now
        self.results: list[dict[str, Any]] = []

    def start(self, meta: dict[str, Any]) -> None:
        write_json(self.run_dir / "run_meta.json", meta)
        self.event("started", **meta)

    def save_targets(self, targets: list[CalibrationTarget]) -> None:
        write_targets(self.run_dir / "targets.json", targets)
        write_targets(self.run_dir / "engagement_targets.json", targets)

    def record_result(self, result: dict[str, Any]) -> None:
        self.results.append(result)
        write_json(self.results_path, self.results)
        write_json(self.run_dir / "engagement_results.json", self.results)
        record_facebook_post_target_result(self.target_health_path, result)

    def finish(self, summary: dict[str, Any]) -> None:
        write_json(self.summary_path, summary)
        self.event("finished", **summary)

    def interrupt(self, visited: int) -> None:
        summary = {
            "status": "interrupted",
            "finished_at": self.utc_now(),
            "visited": visited,
        }
        write_json(self.summary_path, summary)
        self.event("interrupted")

    def fail(self, summary: dict[str, Any]) -> None:
        write_json(self.summary_path, summary)
        self.event("failed", **summary)

    def event(self, kind: str, **payload: Any) -> None:
        append_event(
            self.events_path,
            {"at": self.utc_now(), "kind": kind, **payload},
        )

    @property
    def targets_path(self) -> Path:
        return self.run_dir / "targets.json"

    @property
    def engagement_results_path(self) -> Path:
        return self.run_dir / "engagement_results.json"

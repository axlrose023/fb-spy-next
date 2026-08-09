from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any


@dataclass(slots=True)
class QueuedRelevance:
    source_key: str
    index: int
    raw: dict[str, Any]
    result_path: Path
    attempts: int = 0
    queued_at: float = 0.0
    completed: bool = False


@dataclass(frozen=True, slots=True)
class StreamingSyncState:
    raw_ads: list[dict[str, Any]]
    source_order: list[str]
    source_indexes: dict[str, int]
    accepted: dict[str, dict[str, Any]]
    rejected: dict[str, dict[str, Any]]
    inserted: set[str]

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any
from uuid import UUID

from ..models import Ad


@dataclass(frozen=True, slots=True)
class AdSource:
    token: str
    index: int
    raw: dict[str, Any]


@dataclass(frozen=True, slots=True)
class AdIngestionRequest:
    run_id: UUID
    run_dir: Path
    sources: list[AdSource]
    country_fallback: str | None = None
    replace_existing: bool = False
    upload_media: bool = True


@dataclass(frozen=True, slots=True)
class AdIngestionResult:
    observed: list[Ad]
    inserted: list[Ad]
    inserted_tokens: frozenset[str]
    skipped_count: int

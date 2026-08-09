from __future__ import annotations

import zipfile
from dataclasses import dataclass, field
from pathlib import Path


@dataclass(frozen=True, slots=True)
class AssetRef:
    raw: str
    url: str


@dataclass(slots=True)
class ResourceRecord:
    url: str
    final_url: str
    path: str
    status_code: int
    content_type: str
    bytes: int


@dataclass(slots=True)
class LandingArchiveResult:
    archive_path: Path
    source_url: str
    final_url: str | None = None
    resources: list[ResourceRecord] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return self.archive_path.is_file() and zipfile.is_zipfile(self.archive_path)

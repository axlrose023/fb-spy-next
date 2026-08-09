from __future__ import annotations

from pathlib import Path
from typing import Protocol
from uuid import UUID

from .models import NewRun, Run, RunPage, RunQuery


class RunRepository(Protocol):
    async def page(self, query: RunQuery) -> RunPage: ...

    async def get(self, run_id: UUID, *, refresh: bool = False) -> Run | None: ...

    async def add(self, run: NewRun) -> Run: ...

    async def set_status(self, run_id: UUID, status: str) -> Run | None: ...


class RunTransaction(Protocol):
    async def commit(self) -> None: ...


class RunProcessRunner(Protocol):
    async def start(self, run: Run) -> None: ...

    async def stop(self, run_id: UUID) -> bool: ...


class RunAdsImporter(Protocol):
    async def import_ads(self, run_id: UUID, ads_json_path: Path) -> None: ...


class RunArtifactStager(Protocol):
    async def stage_ads_json(self, source: Path) -> Path | None: ...

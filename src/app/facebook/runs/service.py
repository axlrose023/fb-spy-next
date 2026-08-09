from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from uuid import UUID

from .contracts import (
    RunAdsImporter,
    RunArtifactStager,
    RunProcessRunner,
    RunRepository,
    RunTransaction,
)
from .exceptions import RunArtifactsNotFound, RunNotActive, RunNotFound
from .models import ImportRun, NewRun, Run, RunDefaults, RunPage, RunQuery, StartRun


class RunService:
    def __init__(
        self,
        runs: RunRepository,
        transaction: RunTransaction,
        processes: RunProcessRunner,
        importer: RunAdsImporter,
        stager: RunArtifactStager,
        defaults: RunDefaults,
    ) -> None:
        self._runs = runs
        self._transaction = transaction
        self._processes = processes
        self._importer = importer
        self._stager = stager
        self._defaults = defaults

    async def list_runs(self, query: RunQuery) -> RunPage:
        return await self._runs.page(query)

    async def get_run(self, run_id: UUID) -> Run:
        run = await self._runs.get(run_id)
        if run is None:
            raise RunNotFound
        return run

    async def start_run(self, command: StartRun) -> Run:
        run = await self._runs.add(
            NewRun(
                title=command.title,
                requested_minutes=(command.minutes or self._defaults.minutes),
                collect_scrolls=(
                    command.collect_scrolls or self._defaults.collect_scrolls
                ),
                resolve_max=(
                    command.resolve_max
                    if command.resolve_max is not None
                    else self._defaults.resolve_max
                ),
                scroll_px=command.scroll_px or self._defaults.scroll_px,
                debug=command.debug,
                no_resolve=command.no_resolve,
                no_shots=command.no_shots,
                octo_profile_uuid=(
                    command.octo_profile_uuid or self._defaults.octo_profile_uuid
                ),
            )
        )
        await self._transaction.commit()
        await self._processes.start(run)
        return await self._runs.get(run.id, refresh=True) or run

    async def import_run(self, command: ImportRun) -> Run:
        ads_json_path = await self._stager.stage_ads_json(Path(command.ads_json_path))
        if ads_json_path is None:
            raise RunArtifactsNotFound
        started_at = datetime.now(UTC)
        run = await self._runs.add(
            NewRun(
                status="completed",
                title=command.title or ads_json_path.parent.name,
                ads_json_path=str(ads_json_path),
                runner_run_dir=str(ads_json_path.parent),
                started_at=started_at,
                finished_at=datetime.now(UTC),
            )
        )
        await self._importer.import_ads(run.id, ads_json_path)
        await self._transaction.commit()
        return await self._runs.get(run.id, refresh=True) or run

    async def stop_run(self, run_id: UUID) -> Run:
        await self.get_run(run_id)
        if not await self._processes.stop(run_id):
            raise RunNotActive
        run = await self._runs.set_status(run_id, "stopping")
        if run is None:
            raise RunNotFound
        await self._transaction.commit()
        return run

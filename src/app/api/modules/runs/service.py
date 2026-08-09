from __future__ import annotations

from uuid import UUID

from fastapi import HTTPException

from app.database.uow import UnitOfWork
from app.facebook.runs import (
    RunArtifactsNotFound,
    RunDefaults,
    RunNotActive,
    RunNotFound,
    RunService,
)
from app.facebook.runs.adapters import (
    LegacyRunAdsImporter,
    RunArtifactDirectoryStager,
)
from app.facebook.runs.adapters.persistence import (
    SqlAlchemyRunRepository,
    SqlAlchemyRunTransaction,
)
from app.facebook.runs.adapters.processes import FacebookRunnerRegistry
from app.facebook.runs.schemas import (
    RunImportRequest,
    RunResponse,
    RunsPaginationParams,
    RunsPaginationResponse,
    RunStartRequest,
    to_import_command,
    to_page_response,
    to_query,
    to_response,
    to_start_command,
)
from app.services.facebook.importer import FacebookAdsImporter
from app.settings import Config


class FacebookRunService:
    def __init__(
        self,
        uow: UnitOfWork,
        config: Config,
        importer: FacebookAdsImporter,
        runner_registry: FacebookRunnerRegistry,
    ) -> None:
        self._service = RunService(
            SqlAlchemyRunRepository(uow.session),
            SqlAlchemyRunTransaction(uow.session),
            runner_registry,
            LegacyRunAdsImporter(uow, importer),
            RunArtifactDirectoryStager(config.facebook.data_dir),
            _defaults(config),
        )

    async def get_runs(self, params: RunsPaginationParams) -> RunsPaginationResponse:
        return to_page_response(await self._service.list_runs(to_query(params)))

    async def get_run_by_id(self, run_id: UUID) -> RunResponse:
        try:
            run = await self._service.get_run(run_id)
        except RunNotFound as exc:
            raise HTTPException(status_code=404, detail="Run not found") from exc
        return to_response(run)

    async def start_run(self, request: RunStartRequest) -> RunResponse:
        return to_response(
            await self._service.start_run(to_start_command(request))
        )

    async def import_run(self, request: RunImportRequest) -> RunResponse:
        try:
            run = await self._service.import_run(to_import_command(request))
        except RunArtifactsNotFound as exc:
            raise HTTPException(status_code=404, detail="ads.json not found") from exc
        return to_response(run)

    async def stop_run(self, run_id: UUID) -> RunResponse:
        try:
            run = await self._service.stop_run(run_id)
        except RunNotFound as exc:
            raise HTTPException(status_code=404, detail="Run not found") from exc
        except RunNotActive as exc:
            raise HTTPException(status_code=409, detail="Run is not active") from exc
        return to_response(run)


def _defaults(config: Config) -> RunDefaults:
    facebook = config.facebook
    return RunDefaults(
        minutes=facebook.default_minutes,
        collect_scrolls=facebook.default_collect_scrolls,
        resolve_max=facebook.default_resolve_max,
        scroll_px=facebook.default_scroll_px,
        octo_profile_uuid=facebook.octo_profile_uuid,
    )

import datetime
import shutil
from pathlib import Path
from uuid import UUID

from fastapi import HTTPException

from app.api.common.utils import build_filters
from app.api.modules.runs.models import FacebookRun
from app.api.modules.runs.schema import (
    RunImportRequest,
    RunsPaginationParams,
    RunsPaginationResponse,
    RunStartRequest,
)
from app.database.uow import UnitOfWork
from app.services.facebook import FacebookAdsImporter, FacebookRunnerRegistry
from app.settings import Config


class FacebookRunService:
    def __init__(
        self,
        uow: UnitOfWork,
        config: Config,
        importer: FacebookAdsImporter,
        runner_registry: FacebookRunnerRegistry,
    ):
        self.uow = uow
        self.config = config
        self.importer = importer
        self.runner_registry = runner_registry

    async def get_runs(
        self,
        params: RunsPaginationParams,
    ) -> RunsPaginationResponse:
        data = params.model_dump(exclude_unset=True)
        data.pop("page", None)
        data.pop("page_size", None)
        filters = build_filters(FacebookRun, data)
        runs = await self.uow.facebook_runs.get_all(
            limit=params.page_size,
            offset=params.offset,
            filters=filters,
        )
        total = await self.uow.facebook_runs.get_total_count(filters)
        return RunsPaginationResponse(
            total=total,
            items=runs,
            page=params.page,
            page_size=params.page_size,
        )

    async def get_run_by_id(self, run_id: UUID) -> FacebookRun:
        run = await self.uow.facebook_runs.get_by_id(run_id)
        if not run:
            raise HTTPException(status_code=404, detail="Run not found")
        return run

    async def start_run(self, request: RunStartRequest) -> FacebookRun:
        run = FacebookRun(
            status="created",
            title=request.title,
            requested_minutes=request.minutes or self.config.facebook.default_minutes,
            collect_scrolls=(
                request.collect_scrolls or self.config.facebook.default_collect_scrolls
            ),
            resolve_max=request.resolve_max
            if request.resolve_max is not None
            else self.config.facebook.default_resolve_max,
            scroll_px=request.scroll_px or self.config.facebook.default_scroll_px,
            debug=request.debug,
            no_resolve=request.no_resolve,
            no_shots=request.no_shots,
            octo_profile_uuid=(
                request.octo_profile_uuid or self.config.facebook.octo_profile_uuid
            ),
        )
        await self.uow.facebook_runs.create(run)
        await self.uow.commit()
        await self.runner_registry.start(run)
        await self.uow.refresh(run)
        return run

    async def import_run(self, request: RunImportRequest) -> FacebookRun:
        ads_json_path = self._stage_ads_json(Path(request.ads_json_path))
        if not ads_json_path.exists():
            raise HTTPException(status_code=404, detail="ads.json not found")
        run = FacebookRun(
            status="completed",
            title=request.title or ads_json_path.parent.name,
            ads_json_path=str(ads_json_path),
            runner_run_dir=str(ads_json_path.parent),
            started_at=datetime.datetime.now(datetime.UTC),
            finished_at=datetime.datetime.now(datetime.UTC),
        )
        await self.uow.facebook_runs.create(run)
        await self.importer.import_ads_json(self.uow, run, ads_json_path)
        await self.uow.commit()
        await self.uow.refresh(run)
        return run

    async def stop_run(self, run_id: UUID) -> FacebookRun:
        run = await self.get_run_by_id(run_id)
        stopped = await self.runner_registry.stop(run_id)
        if not stopped:
            raise HTTPException(status_code=409, detail="Run is not active")
        run.status = "stopping"
        await self.uow.commit()
        return run

    def _stage_ads_json(self, ads_json_path: Path) -> Path:
        ads_json_path = ads_json_path.expanduser().resolve()
        data_dir = self.config.facebook.data_dir.resolve()
        if not ads_json_path.exists():
            return ads_json_path
        try:
            ads_json_path.relative_to(data_dir)
            return ads_json_path
        except ValueError:
            pass

        source_run_dir = ads_json_path.parent
        target_run_dir = data_dir / "imports" / source_run_dir.name
        target_run_dir.mkdir(parents=True, exist_ok=True)
        shutil.copy2(ads_json_path, target_run_dir / "ads.json")
        run_meta = source_run_dir / "run_meta.json"
        if run_meta.exists():
            shutil.copy2(run_meta, target_run_dir / "run_meta.json")
        for media_dir in ("screens", "videos", "landing_screens", "landing_archives"):
            source = source_run_dir / media_dir
            if source.exists():
                shutil.copytree(source, target_run_dir / media_dir, dirs_exist_ok=True)
        return target_run_dir / "ads.json"

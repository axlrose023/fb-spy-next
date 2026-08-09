from __future__ import annotations

import asyncio
import shutil
from pathlib import Path
from typing import TYPE_CHECKING, Any
from uuid import UUID

from ..exceptions import RunNotFound

if TYPE_CHECKING:
    from app.database.uow import UnitOfWork


class RunArtifactDirectoryStager:
    def __init__(self, data_dir: Path) -> None:
        self._data_dir = data_dir

    async def stage_ads_json(self, source: Path) -> Path | None:
        return await asyncio.to_thread(self._stage, source)

    def _stage(self, source: Path) -> Path | None:
        ads_json_path = source.expanduser().resolve()
        if not ads_json_path.exists():
            return None
        data_dir = self._data_dir.resolve()
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
            media_source = source_run_dir / media_dir
            if media_source.exists():
                shutil.copytree(
                    media_source,
                    target_run_dir / media_dir,
                    dirs_exist_ok=True,
                )
        return target_run_dir / "ads.json"


class LegacyRunAdsImporter:
    def __init__(self, uow: UnitOfWork, importer: Any) -> None:
        self._uow = uow
        self._importer = importer

    async def import_ads(self, run_id: UUID, ads_json_path: Path) -> None:
        run = await self._uow.facebook_runs.get_by_id(run_id)
        if run is None:
            raise RunNotFound
        await self._importer.import_ads_json(self._uow, run, ads_json_path)

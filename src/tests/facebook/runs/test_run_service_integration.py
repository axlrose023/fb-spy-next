from __future__ import annotations

from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any
from uuid import UUID

import pytest
import pytest_asyncio
from sqlalchemy import delete

from app.database.uow import UnitOfWork
from app.facebook.runs import (
    ImportRun,
    Run,
    RunArtifactsNotFound,
    RunDefaults,
    RunNotActive,
    RunNotFound,
    RunQuery,
    RunService,
    StartRun,
)
from app.facebook.runs.adapters import (
    LegacyRunAdsImporter,
    RunArtifactDirectoryStager,
)
from app.facebook.runs.adapters.persistence import (
    FacebookRun,
    SqlAlchemyRunRepository,
    SqlAlchemyRunTransaction,
)
from app.settings import Config, FacebookConfig, MediaStorageConfig

pytestmark = pytest.mark.integration


class RecordingRunner:
    def __init__(self) -> None:
        self.started: list[Run] = []
        self.stop_result = False
        self.stopped: list[UUID] = []

    async def start(self, run: Run) -> None:
        self.started.append(run)

    async def stop(self, run_id: UUID) -> bool:
        self.stopped.append(run_id)
        return self.stop_result


class RecordingImporter:
    def __init__(self) -> None:
        self.paths: list[Path] = []

    async def import_ads_json(
        self,
        _uow: UnitOfWork,
        run: FacebookRun,
        path: Path,
        **_kwargs: Any,
    ) -> FacebookRun:
        self.paths.append(path)
        run.total_ads = 3
        run.link_ads = 2
        return run


def make_config(tmp_path: Path) -> Config:
    return Config(
        media=MediaStorageConfig(
            backend="local",
            signing_secret="test-media-signing-secret-at-least-32-characters",
        ),
        facebook=FacebookConfig(
            data_dir=tmp_path / "data",
            runner_out_dir=tmp_path / "runs",
            octo_profile_uuid="default-profile",
            default_minutes=15,
            default_collect_scrolls=321,
            default_resolve_max=40,
            default_scroll_px=610,
        ),
    )


@pytest_asyncio.fixture(autouse=True)
async def cleanup_runs(uow: UnitOfWork) -> AsyncIterator[None]:
    yield
    await uow.session.rollback()
    await uow.session.execute(
        delete(FacebookRun).where(FacebookRun.title.like("runs contract%"))
    )
    await uow.session.commit()


def service(
    uow: UnitOfWork,
    tmp_path: Path,
    runner: RecordingRunner,
    importer: RecordingImporter | None = None,
) -> RunService:
    config = make_config(tmp_path)
    facebook = config.facebook
    return RunService(
        SqlAlchemyRunRepository(uow.session),
        SqlAlchemyRunTransaction(uow.session),
        runner,
        LegacyRunAdsImporter(uow, importer or RecordingImporter()),
        RunArtifactDirectoryStager(facebook.data_dir),
        RunDefaults(
            minutes=facebook.default_minutes,
            collect_scrolls=facebook.default_collect_scrolls,
            resolve_max=facebook.default_resolve_max,
            scroll_px=facebook.default_scroll_px,
            octo_profile_uuid=facebook.octo_profile_uuid,
        ),
    )


async def test_start_uses_config_defaults_and_preserves_explicit_zero(
    uow: UnitOfWork,
    tmp_path: Path,
) -> None:
    runner = RecordingRunner()

    run = await service(uow, tmp_path, runner).start_run(
        StartRun(
            title="runs contract start",
            resolve_max=0,
            debug=True,
        )
    )

    assert run.status == "created"
    assert run.requested_minutes == 15
    assert run.collect_scrolls == 321
    assert run.resolve_max == 0
    assert run.scroll_px == 610
    assert run.debug is True
    assert run.octo_profile_uuid == "default-profile"
    assert [item.id for item in runner.started] == [run.id]


async def test_list_filters_and_missing_run_contract(
    uow: UnitOfWork,
    tmp_path: Path,
) -> None:
    runner = RecordingRunner()
    run_service = service(uow, tmp_path, runner)
    await run_service.start_run(StartRun(title="runs contract alpha"))
    await run_service.start_run(StartRun(title="runs contract beta"))

    page = await run_service.list_runs(
        RunQuery(title_search="alpha", page=1, page_size=10)
    )

    assert page.total == 1
    assert [run.title for run in page.items] == ["runs contract alpha"]
    with pytest.raises(RunNotFound):
        await run_service.get_run(UUID("00000000-0000-0000-0000-000000000001"))


async def test_stop_requires_active_process_then_marks_run_stopping(
    uow: UnitOfWork,
    tmp_path: Path,
) -> None:
    runner = RecordingRunner()
    run_service = service(uow, tmp_path, runner)
    run = await run_service.start_run(StartRun(title="runs contract stop"))

    with pytest.raises(RunNotActive):
        await run_service.stop_run(run.id)

    runner.stop_result = True
    stopped = await run_service.stop_run(run.id)

    assert stopped.status == "stopping"
    assert runner.stopped == [run.id, run.id]


async def test_import_stages_external_artifacts_and_updates_run_in_one_flow(
    uow: UnitOfWork,
    tmp_path: Path,
) -> None:
    source = tmp_path / "external-run"
    (source / "screens").mkdir(parents=True)
    (source / "ads.json").write_text("[]", encoding="utf-8")
    (source / "run_meta.json").write_text("{}", encoding="utf-8")
    (source / "screens" / "one.png").write_bytes(b"image")
    runner = RecordingRunner()
    importer = RecordingImporter()
    run_service = service(uow, tmp_path, runner, importer)

    run = await run_service.import_run(
        ImportRun(
            ads_json_path=str(source / "ads.json"),
            title="runs contract import",
        )
    )

    expected = tmp_path / "data" / "imports" / "external-run"
    assert run.status == "completed"
    assert run.total_ads == 3
    assert run.link_ads == 2
    assert importer.paths == [expected / "ads.json"]
    assert (expected / "run_meta.json").exists()
    assert (expected / "screens" / "one.png").read_bytes() == b"image"


async def test_import_missing_ads_json_returns_existing_404_contract(
    uow: UnitOfWork,
    tmp_path: Path,
) -> None:
    run_service = service(uow, tmp_path, RecordingRunner())

    with pytest.raises(RunArtifactsNotFound):
        await run_service.import_run(
            ImportRun(ads_json_path=str(tmp_path / "missing.json"))
        )

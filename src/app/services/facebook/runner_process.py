import asyncio
import datetime
import logging
import math
import os
import signal
import subprocess
from pathlib import Path
from uuid import UUID

from app.api.modules.runs.models import FacebookRun
from app.database.engine import SessionFactory
from app.database.uow import UnitOfWork
from app.services.facebook.importer import FacebookAdsImporter
from app.settings import Config

logger = logging.getLogger(__name__)


class FacebookRunnerRegistry:
    def __init__(self, config: Config, importer: FacebookAdsImporter):
        self.config = config
        self.importer = importer
        self._processes: dict[UUID, subprocess.Popen] = {}

    def is_running(self, run_id: UUID) -> bool:
        process = self._processes.get(run_id)
        return bool(process and process.poll() is None)

    async def start(self, run: FacebookRun) -> None:
        self.config.facebook.data_dir.mkdir(parents=True, exist_ok=True)
        self.config.facebook.runner_out_dir.mkdir(parents=True, exist_ok=True)
        logs_dir = self.config.facebook.data_dir / "logs"
        logs_dir.mkdir(parents=True, exist_ok=True)

        run_dir = self._run_dir(run)
        log_path = logs_dir / f"{run.id}.log"
        command = self._command(run, run_dir)
        env = os.environ.copy()
        env["PYTHONPATH"] = str(self.config.paths.src_path)
        env["PW_TEST_SCREENSHOT_NO_FONTS_READY"] = "1"

        log_file = log_path.open("ab", buffering=0)
        process = subprocess.Popen(
            command,
            cwd=self.config.paths.src_path.parent,
            stdout=log_file,
            stderr=subprocess.STDOUT,
            env=env,
            start_new_session=True,
        )
        self._processes[run.id] = process

        async with SessionFactory() as session:
            async with UnitOfWork(session) as uow:
                db_run = await uow.facebook_runs.get_by_id(run.id)
                if db_run:
                    db_run.status = "running"
                    db_run.process_pid = process.pid
                    db_run.log_path = self._media_relative(log_path)
                    db_run.out_root = str(self.config.facebook.runner_out_dir)
                    db_run.runner_run_dir = str(run_dir)
                    db_run.ads_json_path = str(run_dir / "ads.json")
                    db_run.started_at = datetime.datetime.now(datetime.UTC)
                    await uow.commit()

        asyncio.create_task(self._monitor(run.id, process, run_dir, log_file))

    async def stop(self, run_id: UUID) -> bool:
        process = self._processes.get(run_id)
        if not process or process.poll() is not None:
            return False
        os.killpg(process.pid, signal.SIGTERM)
        return True

    def _command(self, run: FacebookRun, run_dir: Path) -> list[str]:
        octo_profile_uuid = (
            run.octo_profile_uuid or self.config.facebook.octo_profile_uuid
        )
        command = [
            self.config.facebook.runner_python,
            "-m",
            self.config.facebook.runner_module,
            "--minutes",
            str(run.requested_minutes),
            "--collect-scrolls",
            str(run.collect_scrolls),
            "--resolve-max",
            str(run.resolve_max),
            "--scroll-px",
            str(run.scroll_px),
            "--landing-archive-timeout",
            str(self.config.facebook.landing_archive_timeout_seconds),
            "--landing-archive-max-resources",
            str(self.config.facebook.landing_archive_max_resources),
            "--video-max-seconds",
            str(self.config.facebook.video_recording_max_seconds),
            "--video-fps",
            str(self.config.facebook.video_recording_fps),
            "--octo-host",
            self.config.facebook.octo_host,
            "--octo-port",
            str(self.config.facebook.octo_port),
            "--octo-profile-uuid",
            octo_profile_uuid,
            "--run-dir",
            str(run_dir),
        ]
        if run.debug:
            command.append("--debug")
        if self.config.facebook.octo_headless:
            command.append("--octo-headless")
        if run.no_resolve:
            command.append("--no-resolve")
        if run.no_shots:
            command.append("--no-shots")
        if not self.config.facebook.landing_archive_enabled:
            command.append("--no-landing-archives")
        if not self.config.facebook.video_recording_enabled:
            command.append("--no-video-recording")
        return command

    async def _monitor(
        self,
        run_id: UUID,
        process: subprocess.Popen,
        run_dir: Path,
        log_file,
    ) -> None:
        stream = None
        wait_task = asyncio.create_task(asyncio.to_thread(process.wait))
        if self.config.facebook.streaming_import_enabled:
            while not wait_task.done():
                if stream is None:
                    if run_dir.exists():
                        stream = self.importer.create_streaming_session(run_id, run_dir)
                        await self._poll_stream_import(run_id, stream)
                else:
                    await self._poll_stream_import(run_id, stream)
                await asyncio.sleep(self.config.facebook.streaming_import_poll_seconds)

        return_code = await wait_task
        log_file.close()
        self._processes.pop(run_id, None)

        if self.config.facebook.streaming_import_enabled:
            if stream is None:
                ads_json = run_dir / "ads.json"
                if ads_json.exists():
                    stream = self.importer.create_streaming_session(
                        run_id,
                        ads_json.parent,
                        ads_json_path=ads_json,
                    )
            if stream is not None:
                await self._drain_stream_import(run_id, stream)

        async with SessionFactory() as session:
            async with UnitOfWork(session) as uow:
                run = await uow.facebook_runs.get_by_id(run_id)
                if not run:
                    return
                run.return_code = return_code
                run.finished_at = datetime.datetime.now(datetime.UTC)
                self.importer.apply_run_metadata(run, run_dir)
                if stream is not None:
                    await stream.finalize(uow, run)
                else:
                    ads_json = run_dir / "ads.json"
                    if ads_json.exists():
                        await self.importer.import_ads_json(uow, run, ads_json)
                if return_code == 0:
                    run.status = "completed"
                elif run.status in {"running", "stopping"}:
                    run.status = "failed" if run.status == "running" else "stopped"
                    run.error = self._read_tail(run.log_path)
                await uow.commit()

    async def _poll_stream_import(self, run_id: UUID, stream) -> None:
        try:
            async with SessionFactory() as session:
                async with UnitOfWork(session) as uow:
                    run = await uow.facebook_runs.get_by_id(run_id)
                    if not run:
                        return
                    await stream.poll(uow, run)
                    await uow.commit()
        except Exception:
            logger.exception("FB stream import poll failed run_id=%s", run_id)

    async def _drain_stream_import(self, run_id: UUID, stream) -> None:
        deadline = asyncio.get_running_loop().time() + self._stream_drain_timeout(stream)
        while stream.pending_count and asyncio.get_running_loop().time() < deadline:
            await asyncio.sleep(self.config.facebook.streaming_import_poll_seconds)
            await self._poll_stream_import(run_id, stream)
        if stream.pending_count:
            logger.warning(
                "FB stream import final drain timed out run_id=%s pending=%s",
                run_id,
                stream.pending_count,
            )
            stream.expire_pending()
            await self._poll_stream_import(run_id, stream)

    def _stream_drain_timeout(self, stream) -> float:
        if stream.pending_count <= 0:
            return 0.0
        concurrency = max(1, self.config.facebook.relevance_filter_concurrency)
        attempts = max(0, self.config.facebook.relevance_filter_task_retries) + 1
        batches = max(1, math.ceil(stream.pending_count / concurrency))
        return (
            self.config.facebook.relevance_filter_task_timeout_seconds
            * attempts
            * batches
            + 5
        )

    def _run_dir(self, run: FacebookRun) -> Path:
        if run.runner_run_dir:
            return Path(run.runner_run_dir).expanduser().resolve()
        return (self.config.facebook.runner_out_dir / f"run_{run.id}").resolve()

    def _media_relative(self, path: Path) -> str:
        try:
            return path.resolve().relative_to(self.config.facebook.data_dir.resolve()).as_posix()
        except ValueError:
            return str(path)

    def _read_tail(self, relative_path: str | None, limit: int = 4000) -> str | None:
        if not relative_path:
            return None
        path = self.config.facebook.data_dir / relative_path
        if not path.exists():
            return None
        data = path.read_bytes()[-limit:]
        return data.decode(errors="replace")

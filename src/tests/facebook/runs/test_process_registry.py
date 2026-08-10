from __future__ import annotations

import asyncio
import io
from pathlib import Path
from typing import Any, cast
from uuid import uuid4

import pytest

from app.database.uow import UnitOfWork
from app.facebook.runs.adapters import FacebookAdsImporter
from app.facebook.runs.adapters.persistence import FacebookRun
from app.facebook.runs.adapters.processes import FacebookRunnerRegistry
from app.settings import Config, FacebookConfig, MediaStorageConfig

pytestmark = pytest.mark.integration


class FakeProcess:
    def __init__(self, *, pid: int = 4321, return_code: int = 0) -> None:
        self.pid = pid
        self.return_code = return_code
        self.polled: int | None = None

    def poll(self) -> int | None:
        return self.polled

    def wait(self) -> int:
        self.polled = self.return_code
        return self.return_code


class PendingStream:
    def __init__(self, pending_count: int) -> None:
        self.pending_count = pending_count


def config(tmp_path: Path) -> Config:
    return Config(
        media=MediaStorageConfig(
            backend="local",
            signing_secret="test-media-signing-secret-at-least-32-characters",
        ),
        facebook=FacebookConfig(
            data_dir=tmp_path,
            runner_out_dir=tmp_path / "runs",
            octo_profile_uuid="process-profile",
            streaming_import_enabled=False,
            relevance_filter_concurrency=2,
            relevance_filter_task_retries=1,
            relevance_filter_task_timeout_seconds=4,
        ),
    )


async def test_start_records_spawned_pid_and_runtime_paths(
    uow: UnitOfWork,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    active_config = config(tmp_path)
    registry = FacebookRunnerRegistry(
        active_config,
        FacebookAdsImporter(active_config),
    )
    run = FacebookRun(status="created", title="process start contract")
    await uow.facebook_runs.create(run)
    await uow.commit()
    process = FakeProcess()
    spawn: dict[str, Any] = {}

    def fake_popen(command: list[str], **kwargs: Any) -> FakeProcess:
        spawn["command"] = command
        spawn.update(kwargs)
        return process

    async def finished_monitor(*_args: Any, **_kwargs: Any) -> None:
        stdout = spawn.get("stdout")
        if stdout is not None:
            stdout.close()

    monkeypatch.setattr(
        "app.facebook.runs.adapters.processes.registry.subprocess.Popen",
        fake_popen,
    )
    monkeypatch.setattr(registry, "_monitor", finished_monitor)

    await registry.start(run)
    await asyncio.sleep(0)
    await uow.session.refresh(run)

    assert run.status == "running"
    assert run.process_pid == 4321
    assert run.log_path == f"logs/{run.id}.log"
    assert run.runner_run_dir == str((tmp_path / "runs" / f"run_{run.id}").resolve())
    assert spawn["start_new_session"] is True


@pytest.mark.parametrize(
    ("return_code", "expected_status"),
    [(0, "completed"), (2, "failed")],
)
async def test_monitor_persists_return_code_and_terminal_status(
    uow: UnitOfWork,
    tmp_path: Path,
    return_code: int,
    expected_status: str,
) -> None:
    active_config = config(tmp_path)
    registry = FacebookRunnerRegistry(
        active_config,
        FacebookAdsImporter(active_config),
    )
    run_dir = tmp_path / f"monitor-{return_code}"
    run_dir.mkdir()
    run = FacebookRun(
        status="running",
        title=f"process monitor contract {return_code}",
        runner_run_dir=str(run_dir),
    )
    await uow.facebook_runs.create(run)
    await uow.commit()
    process = FakeProcess(return_code=return_code)
    registry._processes[run.id] = cast(Any, process)

    await registry._monitor(run.id, cast(Any, process), run_dir, io.BytesIO())
    await uow.session.refresh(run)

    assert run.return_code == return_code
    assert run.status == expected_status
    assert run.finished_at is not None
    assert run.id not in registry._processes


async def test_stop_signals_process_group_and_rejects_finished_process(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    active_config = config(tmp_path)
    registry = FacebookRunnerRegistry(
        active_config,
        FacebookAdsImporter(active_config),
    )
    run_id = uuid4()
    process = FakeProcess(pid=8080)
    registry._processes[run_id] = cast(Any, process)
    signals: list[tuple[int, int]] = []
    monkeypatch.setattr(
        "app.facebook.runs.adapters.processes.registry.os.killpg",
        lambda pid, signal: signals.append((pid, signal)),
    )

    assert await registry.stop(run_id) is True
    assert signals == [(8080, 15)]

    process.polled = 0
    assert await registry.stop(run_id) is False


def test_stream_drain_timeout_scales_by_batches_and_attempts(tmp_path: Path) -> None:
    active_config = config(tmp_path)
    registry = FacebookRunnerRegistry(
        active_config,
        FacebookAdsImporter(active_config),
    )

    timeout = registry._stream_drain_timeout(PendingStream(pending_count=5))

    assert timeout == 29


def test_process_helpers_preserve_flags_paths_and_log_tail(tmp_path: Path) -> None:
    active_config = Config(
        media=MediaStorageConfig(
            backend="local",
            signing_secret="test-media-signing-secret-at-least-32-characters",
        ),
        facebook=FacebookConfig(
            data_dir=tmp_path / "data",
            runner_out_dir=tmp_path / "runs",
            octo_profile_uuid="fallback-profile",
            octo_headless=True,
            landing_archive_enabled=False,
            video_recording_enabled=False,
        ),
    )
    registry = FacebookRunnerRegistry(
        active_config,
        FacebookAdsImporter(active_config),
    )
    run = FacebookRun(
        status="created",
        requested_minutes=5,
        collect_scrolls=20,
        resolve_max=0,
        scroll_px=500,
        debug=True,
        no_resolve=True,
        no_shots=True,
    )
    explicit_dir = tmp_path / "explicit-run"
    run.runner_run_dir = str(explicit_dir)

    command = registry._command(run, registry._run_dir(run))

    assert registry._run_dir(run) == explicit_dir.resolve()
    assert command[command.index("--octo-profile-uuid") + 1] == "fallback-profile"
    assert command[command.index("--resolve-max") + 1] == "0"
    assert {
        "--debug",
        "--octo-headless",
        "--no-resolve",
        "--no-shots",
        "--no-landing-archives",
        "--no-video-recording",
    }.issubset(command)

    log_path = active_config.facebook.data_dir / "logs" / "tail.log"
    log_path.parent.mkdir(parents=True)
    log_path.write_text("prefix-important-tail", encoding="utf-8")
    assert registry._media_relative(log_path) == "logs/tail.log"
    assert registry._read_tail("logs/tail.log", limit=14) == "important-tail"
    assert registry._read_tail("logs/missing.log") is None
    assert registry._read_tail(None) is None


def test_is_running_reflects_process_state(tmp_path: Path) -> None:
    active_config = config(tmp_path)
    registry = FacebookRunnerRegistry(
        active_config,
        FacebookAdsImporter(active_config),
    )
    run_id = uuid4()
    process = FakeProcess()
    registry._processes[run_id] = cast(Any, process)

    assert registry.is_running(run_id) is True
    process.polled = 0
    assert registry.is_running(run_id) is False
    assert registry.is_running(uuid4()) is False

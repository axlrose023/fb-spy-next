from __future__ import annotations

import os
import signal
import subprocess
import sys
from pathlib import Path
from typing import cast

import pytest

from app.facebook.orchestration.adapters import (
    ProcessRegistry,
    SubprocessCommandRunner,
    signal_process_group,
)

pytestmark = pytest.mark.unit


class FakeProcess:
    def __init__(self, waits: list[int | BaseException]) -> None:
        self.pid = 12345
        self._waits = waits
        self.wait_timeouts: list[float | None] = []
        self.direct_signals: list[signal.Signals] = []

    def wait(self, timeout: float | None = None) -> int:
        self.wait_timeouts.append(timeout)
        result = self._waits.pop(0)
        if isinstance(result, BaseException):
            raise result
        return result

    def send_signal(self, sig: signal.Signals) -> None:
        self.direct_signals.append(sig)


def as_popen(process: FakeProcess) -> subprocess.Popen[bytes]:
    return cast(subprocess.Popen[bytes], process)


def runner(tmp_path: Path, registry: ProcessRegistry) -> SubprocessCommandRunner:
    return SubprocessCommandRunner(
        cwd=tmp_path,
        env={**os.environ, "ORCHESTRATION_TEST_VALUE": "available"},
        registry=registry,
    )


def test_successful_command_uses_configured_environment_and_cwd(
    tmp_path: Path,
) -> None:
    registry = ProcessRegistry()
    log_path = tmp_path / "logs" / "command.log"
    command = [
        sys.executable,
        "-c",
        (
            "import os; "
            "print(os.environ['ORCHESTRATION_TEST_VALUE']); "
            "print(os.getcwd())"
        ),
    ]

    code = runner(tmp_path, registry).run(command, log_path)

    output = log_path.read_text(encoding="utf-8")
    assert code == 0
    assert "available" in output
    assert str(tmp_path) in output
    assert registry.snapshot() == ()


def test_timeout_escalates_process_group_and_clears_registry(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake = FakeProcess(
        [
            subprocess.TimeoutExpired("command", 1),
            subprocess.TimeoutExpired("command", 2),
            subprocess.TimeoutExpired("command", 10),
            0,
        ]
    )
    sent: list[signal.Signals] = []

    def fake_popen(*_args: object, **_kwargs: object) -> FakeProcess:
        return fake

    def record_signal(_process: object, sig: signal.Signals) -> None:
        sent.append(sig)

    monkeypatch.setattr(
        "app.facebook.orchestration.adapters.subprocess_runner.subprocess.Popen",
        fake_popen,
    )
    monkeypatch.setattr(
        "app.facebook.orchestration.adapters.subprocess_runner.signal_process_group",
        record_signal,
    )
    registry = ProcessRegistry()
    log_path = tmp_path / "timeout.log"

    code = runner(tmp_path, registry).run(
        ["command"],
        log_path,
        timeout_seconds=1,
        interrupt_grace_seconds=2,
    )

    assert code == 124
    assert sent == [signal.SIGINT, signal.SIGTERM, signal.SIGKILL]
    assert fake.wait_timeouts == [1, 2, 10, None]
    assert registry.snapshot() == ()
    output = log_path.read_text(encoding="utf-8")
    assert "command timeout" in output
    assert "SIGINT grace expired" in output
    assert "SIGTERM grace expired" in output


def test_keyboard_interrupt_is_forwarded_and_registry_is_cleared(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake = FakeProcess(
        [
            KeyboardInterrupt(),
            subprocess.TimeoutExpired("command", 2),
        ]
    )
    sent: list[signal.Signals] = []

    def fake_popen(*_args: object, **_kwargs: object) -> FakeProcess:
        return fake

    def record_signal(_process: object, sig: signal.Signals) -> None:
        sent.append(sig)

    monkeypatch.setattr(
        "app.facebook.orchestration.adapters.subprocess_runner.subprocess.Popen",
        fake_popen,
    )
    monkeypatch.setattr(
        "app.facebook.orchestration.adapters.subprocess_runner.signal_process_group",
        record_signal,
    )
    registry = ProcessRegistry()

    with pytest.raises(KeyboardInterrupt):
        runner(tmp_path, registry).run(
            ["command"],
            tmp_path / "interrupt.log",
            interrupt_grace_seconds=2,
        )

    assert sent == [signal.SIGINT, signal.SIGTERM]
    assert registry.snapshot() == ()


def test_process_group_signal_falls_back_to_direct_process_signal(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake = FakeProcess([0])

    def fail_killpg(_pid: int, _sig: signal.Signals) -> None:
        raise OSError("process group unavailable")

    monkeypatch.setattr(
        "app.facebook.orchestration.adapters.subprocess_runner.os.killpg",
        fail_killpg,
    )

    signal_process_group(as_popen(fake), signal.SIGTERM)

    assert fake.direct_signals == [signal.SIGTERM]


def test_missing_process_group_is_ignored_without_direct_signal(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake = FakeProcess([0])

    def missing_killpg(_pid: int, _sig: signal.Signals) -> None:
        raise ProcessLookupError

    monkeypatch.setattr(
        "app.facebook.orchestration.adapters.subprocess_runner.os.killpg",
        missing_killpg,
    )

    signal_process_group(as_popen(fake), signal.SIGINT)

    assert fake.direct_signals == []


def test_registry_signals_every_active_process_from_a_snapshot(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    first = FakeProcess([0])
    second = FakeProcess([0])
    registry = ProcessRegistry()
    registry.register(as_popen(first))
    registry.register(as_popen(second))
    sent: list[tuple[int, signal.Signals]] = []

    def record_signal(process: subprocess.Popen[bytes], sig: signal.Signals) -> None:
        sent.append((process.pid, sig))

    monkeypatch.setattr(
        "app.facebook.orchestration.adapters.subprocess_runner.signal_process_group",
        record_signal,
    )

    registry.signal_all(signal.SIGINT)

    assert sent == [(12345, signal.SIGINT), (12345, signal.SIGINT)]
    registry.discard(as_popen(first))
    registry.discard(as_popen(second))
    assert registry.snapshot() == ()

from __future__ import annotations

import os
import signal
import subprocess
import threading
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import BinaryIO


class ProcessRegistry:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._processes: set[subprocess.Popen[bytes]] = set()

    def register(self, process: subprocess.Popen[bytes]) -> None:
        with self._lock:
            self._processes.add(process)

    def discard(self, process: subprocess.Popen[bytes]) -> None:
        with self._lock:
            self._processes.discard(process)

    def snapshot(self) -> tuple[subprocess.Popen[bytes], ...]:
        with self._lock:
            return tuple(self._processes)

    def signal_all(self, sig: signal.Signals) -> None:
        for process in self.snapshot():
            signal_process_group(process, sig)


class SubprocessCommandRunner:
    def __init__(
        self,
        *,
        cwd: Path,
        env: Mapping[str, str],
        registry: ProcessRegistry,
    ) -> None:
        self._cwd = cwd
        self._env = dict(env)
        self._registry = registry

    def run(
        self,
        command: Sequence[str],
        log_path: Path,
        *,
        timeout_seconds: float | None = None,
        interrupt_grace_seconds: float = 30.0,
    ) -> int:
        log_path.parent.mkdir(parents=True, exist_ok=True)
        with log_path.open("ab", buffering=0) as log_file:
            process = subprocess.Popen(
                list(command),
                cwd=self._cwd,
                stdout=log_file,
                stderr=subprocess.STDOUT,
                env=self._env,
                start_new_session=True,
            )
            self._registry.register(process)
            try:
                return process.wait(timeout=timeout_seconds)
            except subprocess.TimeoutExpired:
                write_log_line(
                    log_file,
                    f"[orchestrator] command timeout after "
                    f"{timeout_seconds:.1f}s; sending SIGINT",
                )
                signal_process_group(process, signal.SIGINT)
                try:
                    process.wait(timeout=interrupt_grace_seconds)
                except subprocess.TimeoutExpired:
                    write_log_line(
                        log_file,
                        "[orchestrator] SIGINT grace expired; sending SIGTERM",
                    )
                    signal_process_group(process, signal.SIGTERM)
                    try:
                        process.wait(timeout=10)
                    except subprocess.TimeoutExpired:
                        write_log_line(
                            log_file,
                            "[orchestrator] SIGTERM grace expired; sending SIGKILL",
                        )
                        signal_process_group(process, signal.SIGKILL)
                        process.wait()
                return 124
            except KeyboardInterrupt:
                write_log_line(
                    log_file,
                    "[orchestrator] interrupted; forwarding SIGINT",
                )
                signal_process_group(process, signal.SIGINT)
                try:
                    process.wait(timeout=interrupt_grace_seconds)
                except subprocess.TimeoutExpired:
                    signal_process_group(process, signal.SIGTERM)
                raise
            finally:
                self._registry.discard(process)


def write_log_line(log_file: BinaryIO, message: str) -> None:
    log_file.write(f"\n{message}\n".encode())


def signal_process_group(
    process: subprocess.Popen[bytes],
    sig: signal.Signals,
) -> None:
    try:
        os.killpg(process.pid, sig)
    except ProcessLookupError:
        pass
    except OSError:
        try:
            process.send_signal(sig)
        except OSError:
            pass

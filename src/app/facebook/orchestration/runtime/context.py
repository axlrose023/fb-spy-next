from __future__ import annotations

import signal
import threading
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from types import FrameType

from app.settings import Config, get_config

from ..adapters import ProcessRegistry, run_orchestrator_command

ConfigProvider = Callable[[], Config]
Output = Callable[[str, bool], None]


def console_output(message: str, flush: bool = False) -> None:
    print(message, flush=flush)


@dataclass(slots=True)
class RuntimeContext:
    config_provider: ConfigProvider = get_config
    process_registry: ProcessRegistry = field(default_factory=ProcessRegistry)
    stop_event: threading.Event = field(default_factory=threading.Event)
    output: Output = console_output

    @property
    def config(self) -> Config:
        return self.config_provider()

    def log(self, message: str) -> None:
        self.output(message, True)

    def run_command(
        self,
        command: Sequence[str],
        log_path: Path,
        *,
        timeout_seconds: float | None = None,
        interrupt_grace_seconds: float = 30.0,
    ) -> int:
        result: int = run_orchestrator_command(
            command,
            log_path,
            src_path=self.config.paths.src_path,
            registry=self.process_registry,
            timeout_seconds=timeout_seconds,
            interrupt_grace_seconds=interrupt_grace_seconds,
        )
        return result

    def request_stop(self, _signum: int, _frame: FrameType | None) -> None:
        self.stop_event.set()
        self.process_registry.signal_all(signal.SIGINT)


DEFAULT_CONTEXT = RuntimeContext()

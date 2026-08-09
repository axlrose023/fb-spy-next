from __future__ import annotations

import os
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Protocol

from app.facebook.settings import FacebookConfig

from .command_environment import OctoProcessEnvironment, PythonProcessEnvironment
from .subprocess_runner import ProcessRegistry, SubprocessCommandRunner


class OctoRuntimeOptions(Protocol):
    octo_host: str
    octo_port: int
    octo_headless: bool | None


def python_process_environment(settings: FacebookConfig) -> PythonProcessEnvironment:
    return PythonProcessEnvironment(executable=settings.runner_python)


def octo_headless(
    explicit: bool | None,
    settings: FacebookConfig,
) -> bool:
    return bool(settings.octo_headless if explicit is None else explicit)


def octo_process_environment(
    options: OctoRuntimeOptions,
    settings: FacebookConfig,
) -> OctoProcessEnvironment:
    return OctoProcessEnvironment(
        executable=settings.runner_python,
        collector_module=settings.runner_module,
        host=options.octo_host or settings.octo_host,
        port=options.octo_port or settings.octo_port,
        headless=octo_headless(options.octo_headless, settings),
    )


def relevance_classification_enabled(
    explicit: bool | None,
    settings: FacebookConfig,
) -> bool:
    if explicit is not None:
        return bool(explicit)
    return bool(settings.relevance_filter_enabled)


def run_orchestrator_command(
    command: Sequence[str],
    log_path: Path,
    *,
    src_path: Path,
    registry: ProcessRegistry,
    timeout_seconds: float | None = None,
    interrupt_grace_seconds: float = 30.0,
    environ: Mapping[str, str] | None = None,
) -> int:
    process_environment = dict(os.environ if environ is None else environ)
    process_environment.setdefault("PYTHONPATH", str(src_path))
    process_environment["PW_TEST_SCREENSHOT_NO_FONTS_READY"] = "1"
    result: int = SubprocessCommandRunner(
        cwd=src_path.parent,
        env=process_environment,
        registry=registry,
    ).run(
        command,
        log_path,
        timeout_seconds=timeout_seconds,
        interrupt_grace_seconds=interrupt_grace_seconds,
    )
    return result

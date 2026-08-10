from __future__ import annotations

import sys
from dataclasses import dataclass
from pathlib import Path

import pytest

from app.facebook.orchestration.adapters import (
    ProcessRegistry,
    octo_headless,
    octo_process_environment,
    python_process_environment,
    relevance_classification_enabled,
    run_orchestrator_command,
)
from app.facebook.settings import FacebookConfig

pytestmark = pytest.mark.unit


def test_default_collector_module_is_canonical() -> None:
    assert FacebookConfig().runner_module == "app.facebook.collection.commands"


@dataclass
class OctoOptions:
    octo_host: str = ""
    octo_port: int = 0
    octo_headless: bool | None = None


def test_process_environments_preserve_config_fallback_and_cli_override() -> None:
    settings = FacebookConfig(
        runner_python="/configured/python",
        runner_module="configured.runner",
        octo_host="configured-host",
        octo_port=58888,
        octo_headless=True,
    )

    python_environment = python_process_environment(settings)
    configured = octo_process_environment(OctoOptions(), settings)
    overridden = octo_process_environment(
        OctoOptions(
            octo_host="cli-host",
            octo_port=59999,
            octo_headless=False,
        ),
        settings,
    )

    assert python_environment.executable == "/configured/python"
    assert configured.host == "configured-host"
    assert configured.port == 58888
    assert configured.headless is True
    assert configured.collector_module == "configured.runner"
    assert overridden.host == "cli-host"
    assert overridden.port == 59999
    assert overridden.headless is False
    assert octo_headless(None, settings) is True
    assert octo_headless(False, settings) is False


def test_relevance_flag_overrides_configured_default() -> None:
    enabled = FacebookConfig(relevance_filter_enabled=True)
    disabled = FacebookConfig(relevance_filter_enabled=False)

    assert relevance_classification_enabled(None, enabled) is True
    assert relevance_classification_enabled(None, disabled) is False
    assert relevance_classification_enabled(False, enabled) is False
    assert relevance_classification_enabled(True, disabled) is True


def test_orchestrator_command_sets_cwd_and_required_environment(
    tmp_path: Path,
) -> None:
    src_path = tmp_path / "project" / "src"
    src_path.mkdir(parents=True)
    log_path = tmp_path / "command.log"
    code = run_orchestrator_command(
        [
            sys.executable,
            "-c",
            (
                "import os; "
                "print(os.getcwd()); "
                "print(os.environ['PYTHONPATH']); "
                "print(os.environ['PW_TEST_SCREENSHOT_NO_FONTS_READY'])"
            ),
        ],
        log_path,
        src_path=src_path,
        registry=ProcessRegistry(),
        environ={},
    )

    assert code == 0
    assert log_path.read_text(encoding="utf-8").splitlines() == [
        str(src_path.parent),
        str(src_path),
        "1",
    ]

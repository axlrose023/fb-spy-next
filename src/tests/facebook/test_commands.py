from __future__ import annotations

import subprocess
import sys
from collections.abc import Sequence
from pathlib import Path

import pytest

from app.facebook import commands

pytestmark = pytest.mark.unit


def test_gateway_forwards_remaining_arguments_to_lazy_command(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[tuple[str, list[str]]] = []

    def load_main(module_name: str) -> commands.CommandMain:
        def run(argv: Sequence[str] | None = None) -> int:
            calls.append((module_name, list(argv or ())))
            return 17

        return run

    monkeypatch.setattr(commands, "_load_main", load_main)

    result = commands.main(["classify", "--run-dir", "one", "--force"])

    assert result == 17
    assert calls == [
        (
            "app.facebook.relevance.commands",
            ["--run-dir", "one", "--force"],
        )
    ]


def test_gateway_without_command_prints_help(
    capsys: pytest.CaptureFixture[str],
) -> None:
    assert commands.main([]) == 2
    assert "COMMAND" in capsys.readouterr().out


@pytest.mark.parametrize("command", [item.name for item in commands.COMMANDS])
def test_gateway_subcommand_help_is_executable(command: str) -> None:
    completed = subprocess.run(
        [sys.executable, "-m", "app.facebook.commands", command, "--help"],
        cwd=Path(__file__).parents[3],
        capture_output=True,
        text=True,
        timeout=15,
        check=False,
    )

    assert completed.returncode == 0, completed.stderr
    assert "usage:" in completed.stdout
    assert "RuntimeWarning" not in completed.stderr

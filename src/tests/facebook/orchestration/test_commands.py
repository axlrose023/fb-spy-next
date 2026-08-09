from __future__ import annotations

import subprocess
import sys
from argparse import Namespace
from collections.abc import Callable
from importlib import import_module
from typing import Any

import pytest

from app.facebook.orchestration.commands import CommandHandlers, build_parser, dispatch
from app.services import facebook_orchestrator

pytestmark = pytest.mark.unit


def test_legacy_orchestrator_uses_canonical_parser() -> None:
    assert facebook_orchestrator._build_parser is build_parser
    assert facebook_orchestrator._dispatch_command is dispatch


def test_commands_package_does_not_load_legacy_orchestrator() -> None:
    result = subprocess.run(
        [
            sys.executable,
            "-c",
            (
                "import sys; "
                "import app.facebook.orchestration.commands; "
                "assert 'app.services.facebook_orchestrator' not in sys.modules"
            ),
        ],
        check=False,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0, result.stderr


def test_run_parser_reads_offer_defaults_from_environment(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv(
        "FACEBOOK_CALIBRATION_OFFER_SUBMIT_ALLOW_DOMAINS",
        " one.test, ,two.test ",
    )
    monkeypatch.setenv(
        "FACEBOOK_CALIBRATION_OFFER_IDENTITY_JSON",
        "/tmp/identity.json",
    )

    args = build_parser().parse_args(["run"])

    assert args.calibration_offer_submit_allow_domain == [
        "one.test",
        "two.test",
    ]
    assert args.calibration_offer_identity_json == "/tmp/identity.json"


class HandlerHarness:
    def __init__(self) -> None:
        self.calls: list[tuple[str, str]] = []

    def handler(self, name: str, result: int) -> Callable[[Namespace], int]:
        def handle(args: Namespace) -> int:
            self.calls.append((name, str(args.command)))
            return result

        return handle

    def handlers(self) -> CommandHandlers:
        return CommandHandlers(
            run=self.handler("run", 11),
            evaluate=self.handler("evaluate", 12),
            seed_baseline=self.handler("seed", 13),
            discover_active=self.handler("active", 14),
            discover_public=self.handler("public", 15),
        )


def test_run_dispatch_installs_signal_handlers(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    harness = HandlerHarness()
    installed: list[tuple[Any, Any]] = []
    dispatch_module = import_module("app.facebook.orchestration.commands.dispatch")
    monkeypatch.setattr(
        dispatch_module.signal,
        "signal",
        lambda sig, handler: installed.append((sig, handler)),
    )

    result = dispatch(
        ["run"],
        handlers=harness.handlers(),
        request_stop=facebook_orchestrator._request_orchestrator_stop,
    )

    assert result == 11
    assert harness.calls == [("run", "run")]
    assert [item[0] for item in installed] == [
        dispatch_module.signal.SIGINT,
        dispatch_module.signal.SIGTERM,
    ]


@pytest.mark.parametrize(
    ("argv", "expected_result", "expected_call"),
    [
        (["evaluate", "--run-dir", "/tmp/run"], 12, ("evaluate", "evaluate")),
        (
            ["seed-baseline", "--run-dir", "/tmp/run", "--profile-uuid", "p"],
            13,
            ("seed", "seed-baseline"),
        ),
        (["discover-active"], 14, ("active", "discover-active")),
        (["discover-octo"], 15, ("public", "discover-octo")),
    ],
)
def test_maintenance_dispatch_routes_exact_handler(
    argv: list[str],
    expected_result: int,
    expected_call: tuple[str, str],
) -> None:
    harness = HandlerHarness()

    result = dispatch(
        argv,
        handlers=harness.handlers(),
        request_stop=facebook_orchestrator._request_orchestrator_stop,
    )

    assert result == expected_result
    assert harness.calls == [expected_call]


def test_missing_command_prints_help_and_returns_two(
    capsys: pytest.CaptureFixture[str],
) -> None:
    harness = HandlerHarness()

    result = dispatch(
        [],
        handlers=harness.handlers(),
        request_stop=facebook_orchestrator._request_orchestrator_stop,
    )

    assert result == 2
    assert harness.calls == []
    assert "Profile-level Facebook collector orchestrator" in capsys.readouterr().out

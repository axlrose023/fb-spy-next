"""Canonical command gateway for Facebook automation workflows."""

from __future__ import annotations

import argparse
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from importlib import import_module
from typing import cast


@dataclass(frozen=True, slots=True)
class CommandSpec:
    name: str
    module: str
    help: str


COMMANDS = (
    CommandSpec("collect", "app.facebook.collection.commands", "Collect feed ads."),
    CommandSpec(
        "orchestrate",
        "app.services.facebook_orchestrator",
        "Run profile orchestration cycles.",
    ),
    CommandSpec(
        "calibrate",
        "app.facebook.calibration.commands",
        "Calibrate one profile from saved relevant ads.",
    ),
    CommandSpec(
        "classify",
        "app.facebook.relevance.commands",
        "Classify one collected run.",
    ),
    CommandSpec(
        "enrich",
        "app.facebook.enrichment.commands",
        "Capture artifacts for relevance-gated ads.",
    ),
    CommandSpec(
        "resolve-landing",
        "app.facebook.relevance.evidence.browser_command",
        "Resolve uncertain landings in an isolated context.",
    ),
    CommandSpec(
        "import-run",
        "app.facebook.runs.commands",
        "Import one classified run into the backend.",
    ),
)

CommandMain = Callable[[Sequence[str] | None], int]


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", metavar="COMMAND")
    for command in COMMANDS:
        subparsers.add_parser(command.name, add_help=False, help=command.help)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args, command_argv = parser.parse_known_args(argv)
    if args.command is None:
        parser.print_help()
        return 2
    command = next(item for item in COMMANDS if item.name == args.command)
    return _load_main(command.module)(command_argv)


def _load_main(module_name: str) -> CommandMain:
    main_function = import_module(module_name).main
    return cast(CommandMain, main_function)


if __name__ == "__main__":
    raise SystemExit(main())

"""Resolve uncertain ad landings without using the authenticated FB context."""

from __future__ import annotations

import argparse
from collections.abc import Sequence
from pathlib import Path
from typing import cast

from ..adapters.isolated_browser import run_isolated_browser


def main(argv: Sequence[str] | None = None) -> int:
    return cast(int, run_isolated_browser(build_parser().parse_args(argv)))


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-dir", type=Path, required=True)
    parser.add_argument("--source", type=Path, default=None)
    parser.add_argument("--output", type=Path, default=None)
    parser.add_argument("--octo-host", default="127.0.0.1")
    parser.add_argument("--octo-port", type=int, default=58888)
    parser.add_argument("--octo-profile-uuid", default="")
    parser.add_argument("--octo-headless", action="store_true")
    parser.add_argument("--timeout-ms", type=int, default=30_000)
    parser.add_argument("--landing-ready-seconds", type=float, default=12.0)
    parser.add_argument("--landing-archive-max-resources", type=int, default=80)
    parser.add_argument(
        "--archive-landings",
        action=argparse.BooleanOptionalAction,
        default=False,
    )
    return parser


if __name__ == "__main__":
    raise SystemExit(main())

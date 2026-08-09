"""Collect sponsored posts from one Facebook profile feed."""

from __future__ import annotations

import signal
from collections.abc import Sequence
from typing import Any

from .cli import build_parser


def request_stop(signum: int, frame: Any) -> None:
    # The feed loop remains in the compatibility runner until the next unit.
    from app.services import facebook_runner

    facebook_runner._request_stop(signum, frame)


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    signal.signal(signal.SIGINT, request_stop)
    signal.signal(signal.SIGTERM, request_stop)

    # Keep --help independent from the transitional runner import.
    from .cli.runtime import run_command

    return run_command(args)


if __name__ == "__main__":
    raise SystemExit(main())

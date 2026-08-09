"""Calibrate one profile using previously classified relevant ads.

The calibrator never discovers or classifies ads. It reopens saved Facebook
posts when available and can continue through their saved relevant offer in the
same Octo context. Every attempted action is written to private audit artifacts.
"""

from __future__ import annotations

import signal
from collections.abc import Sequence
from typing import cast

from .cli import build_parser, run_command, validate_args

STOP_REQUESTED = False


def request_stop(signum: int, _frame: object) -> None:
    global STOP_REQUESTED
    STOP_REQUESTED = True
    raise KeyboardInterrupt(f"signal {signum}")


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    validate_args(args, parser)
    signal.signal(signal.SIGINT, request_stop)
    signal.signal(signal.SIGTERM, request_stop)
    return cast(int, run_command(args, stop_requested=lambda: STOP_REQUESTED))


if __name__ == "__main__":
    raise SystemExit(main())

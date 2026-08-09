from __future__ import annotations

import argparse
import signal
from collections.abc import Sequence
from pathlib import Path
from typing import Any, cast

from .adapters.playwright.runtime import run

STOP_REQUESTED = False


def request_stop(signum: int, _frame: Any) -> None:
    global STOP_REQUESTED
    STOP_REQUESTED = True
    raise KeyboardInterrupt(f"signal {signum}")


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    signal.signal(signal.SIGINT, request_stop)
    signal.signal(signal.SIGTERM, request_stop)
    return cast(int, run(args, stop_requested=lambda: STOP_REQUESTED))


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Actively enrich only ads allowed by the passive Facebook relevance gate."
    )
    parser.add_argument("--run-dir", type=Path, required=True)
    parser.add_argument("--source", type=Path, default=None)
    parser.add_argument("--output", type=Path, default=None)
    parser.add_argument("--octo-host", default="127.0.0.1")
    parser.add_argument("--octo-port", type=int, default=58888)
    parser.add_argument("--octo-profile-uuid", default="")
    parser.add_argument("--octo-headless", action="store_true")
    parser.add_argument("--timeout-ms", type=int, default=45_000)
    parser.add_argument("--locate-timeout-ms", type=int, default=12_000)
    parser.add_argument("--wait-after-load", type=float, default=2.0)
    parser.add_argument(
        "--record-videos",
        action=argparse.BooleanOptionalAction,
        default=True,
    )
    parser.add_argument("--video-max-seconds", type=float, default=10.0)
    parser.add_argument(
        "--resolve-landings",
        action=argparse.BooleanOptionalAction,
        default=True,
    )
    parser.add_argument("--landing-archive-timeout", type=float, default=20.0)
    parser.add_argument("--landing-archive-max-resources", type=int, default=120)
    return parser


if __name__ == "__main__":
    raise SystemExit(main())

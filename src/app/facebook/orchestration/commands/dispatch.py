from __future__ import annotations

import argparse
import signal
from collections.abc import Callable, Sequence
from types import FrameType

from .models import CommandHandlers
from .parser import build_parser

StopHandler = Callable[[int, FrameType | None], None]
ParserFactory = Callable[[], argparse.ArgumentParser]


def dispatch(
    argv: Sequence[str] | None,
    *,
    handlers: CommandHandlers,
    request_stop: StopHandler,
    parser_factory: ParserFactory = build_parser,
) -> int:
    parser = parser_factory()
    args = parser.parse_args(argv)
    if args.command == "run":
        signal.signal(signal.SIGINT, request_stop)
        signal.signal(signal.SIGTERM, request_stop)
        return handlers.run(args)
    if args.command == "evaluate":
        return handlers.evaluate(args)
    if args.command == "seed-baseline":
        return handlers.seed_baseline(args)
    if args.command == "discover-active":
        return handlers.discover_active(args)
    if args.command == "discover-octo":
        return handlers.discover_public(args)
    parser.print_help()
    return 2

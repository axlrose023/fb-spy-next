"""Classify one collector run without importing it into the backend database."""

from __future__ import annotations

import argparse
from pathlib import Path
from typing import Any

from app.settings import get_config

from .classification.command import run_finalize, run_prefilter, run_standard
from .evidence.command import run_resolve_holds
from .files import source_path


def main() -> int:
    args = build_parser().parse_args()
    run_dir = args.run_dir.expanduser().resolve()
    source = source_path(run_dir, args.stage, args.source)
    config = get_config()
    handlers: dict[str, Any] = {
        "standard": run_standard,
        "prefilter": run_prefilter,
        "resolve-holds": run_resolve_holds,
        "finalize": run_finalize,
    }
    return int(handlers[args.stage](args, run_dir, source, config))


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-dir", type=Path, required=True)
    parser.add_argument(
        "--stage",
        choices=("standard", "prefilter", "resolve-holds", "finalize"),
        default="standard",
    )
    parser.add_argument("--source", type=Path, default=None)
    parser.add_argument("--force", action="store_true")
    parser.add_argument("--include-video", action="store_true")
    return parser


if __name__ == "__main__":
    raise SystemExit(main())

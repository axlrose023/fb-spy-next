from __future__ import annotations

import argparse
from typing import Any


def add_maintenance_commands(sub: Any) -> None:
    evaluate = sub.add_parser("evaluate", help="Evaluate one existing collect run.")
    add_common_paths(evaluate)
    evaluate.add_argument("--run-dir", required=True)
    evaluate.add_argument("--profile-uuid", default="")
    evaluate.add_argument("--expected-country", default="")
    evaluate.add_argument("--return-code", type=int)
    evaluate.add_argument("--default-elapsed-seconds", type=float)
    evaluate.add_argument("--default-scrolls", type=int)
    evaluate.add_argument("--calibration-targets", type=int)

    seed = sub.add_parser(
        "seed-baseline", help="Record an existing good run as baseline."
    )
    add_common_paths(seed)
    seed.add_argument("--run-dir", required=True)
    seed.add_argument("--profile-uuid", required=True)
    seed.add_argument("--label", default="")
    seed.add_argument("--expected-country", default="")
    seed.add_argument("--default-elapsed-seconds", type=float)
    seed.add_argument("--default-scrolls", type=int)

    discover = sub.add_parser(
        "discover-active", help="Merge active Octo profiles into profiles JSON."
    )
    discover.add_argument(
        "--profiles-json", default="storage/facebook/orchestrator/profiles.json"
    )
    discover.add_argument("--octo-host", default="127.0.0.1")
    discover.add_argument("--octo-port", type=int, default=58888)
    discover.add_argument("--enable-new", action="store_true")

    discover_public = sub.add_parser(
        "discover-octo", help="Merge Octo Public API profiles into profiles JSON."
    )
    discover_public.add_argument(
        "--profiles-json", default="storage/facebook/orchestrator/profiles.json"
    )
    discover_public.add_argument("--octo-api-token", default="")
    discover_public.add_argument("--octo-search-tags", default="")
    discover_public.add_argument("--enable-new", action="store_true")


def add_common_paths(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--root-dir", default="storage/facebook/orchestrator")
    parser.add_argument(
        "--state-json", default="storage/facebook/orchestrator/state.json"
    )

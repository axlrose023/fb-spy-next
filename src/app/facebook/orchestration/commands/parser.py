from __future__ import annotations

import argparse

from .maintenance_options import add_maintenance_commands
from .run_options import add_run_command

DESCRIPTION = """Profile-level Facebook collector orchestrator.

This is intentionally a thin CLI layer over the existing runner and calibrator.
It keeps state in JSON files, runs one job per Octo profile at a time, and does
not require backend or frontend changes.
"""


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=DESCRIPTION)
    subparsers = parser.add_subparsers(dest="command")
    add_run_command(subparsers)
    add_maintenance_commands(subparsers)
    return parser

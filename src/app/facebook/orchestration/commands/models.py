from __future__ import annotations

import argparse
from collections.abc import Callable
from dataclasses import dataclass

CommandHandler = Callable[[argparse.Namespace], int]


@dataclass(frozen=True, slots=True)
class CommandHandlers:
    run: CommandHandler
    evaluate: CommandHandler
    seed_baseline: CommandHandler
    discover_active: CommandHandler
    discover_public: CommandHandler

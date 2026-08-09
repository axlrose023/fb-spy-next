from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class OrchestrationRunRequest:
    continuous: bool


@dataclass(frozen=True, slots=True)
class OrchestrationRunHooks:
    discover_profiles: Callable[[], None]
    run_once: Callable[[], int]
    run_continuously: Callable[[], int]


class OrchestrationService:
    def __init__(self, hooks: OrchestrationRunHooks) -> None:
        self._hooks = hooks

    def run(self, request: OrchestrationRunRequest) -> int:
        self._hooks.discover_profiles()
        if request.continuous:
            return self._hooks.run_continuously()
        return self._hooks.run_once()

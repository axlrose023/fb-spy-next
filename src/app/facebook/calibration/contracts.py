from __future__ import annotations

from typing import Any, Protocol

from .planning import CalibrationTarget


class CalibrationTargetExecutor(Protocol):
    def execute(
        self,
        target: CalibrationTarget,
        *,
        index: int,
        total: int,
    ) -> dict[str, Any]: ...


class CalibrationResultRecorder(Protocol):
    def __call__(self, result: dict[str, Any], /) -> None: ...


class StopRequested(Protocol):
    def __call__(self, /) -> bool: ...


class MonotonicClock(Protocol):
    def __call__(self, /) -> float: ...


class Sleeper(Protocol):
    def __call__(self, seconds: float, /) -> None: ...

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from .contracts import RunProcessRunner, RunRepository
from .exceptions import RunArtifactsNotFound, RunNotActive, RunNotFound
from .metrics import RunMetrics, collect_run_metrics, parse_datetime
from .models import (
    ImportRun,
    NewRun,
    Run,
    RunDefaults,
    RunPage,
    RunQuery,
    StartRun,
)
from .service import RunService

if TYPE_CHECKING:
    from .adapters.persistence import FacebookRun as FacebookRunRecord

__all__ = [
    "ImportRun",
    "FacebookRunRecord",
    "NewRun",
    "Run",
    "RunArtifactsNotFound",
    "RunDefaults",
    "RunMetrics",
    "RunNotActive",
    "RunNotFound",
    "RunPage",
    "RunProcessRunner",
    "RunQuery",
    "RunRepository",
    "RunService",
    "StartRun",
    "collect_run_metrics",
    "parse_datetime",
]


def __getattr__(name: str) -> Any:
    if name != "FacebookRunRecord":
        raise AttributeError(name)
    from .adapters.persistence import FacebookRun

    globals()[name] = FacebookRun
    return FacebookRun

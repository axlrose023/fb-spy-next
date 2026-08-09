from __future__ import annotations

from pathlib import Path
from typing import Any, Protocol

from .models import EnrichmentResult, RelevantAd


class RelevantAdExecutor(Protocol):
    def enrich(
        self,
        context: Any,
        ad: RelevantAd,
        *,
        sequence: int,
        run_dir: Path,
    ) -> EnrichmentResult: ...

from __future__ import annotations

from typing import Any

from .candidates import CandidateRegistry
from .feed import ad_from_detection
from .models import CandidateDecision


class CollectionService:
    def __init__(self, registry: CandidateRegistry | None = None) -> None:
        self.registry = registry or CandidateRegistry()

    def consider_detection(
        self,
        raw: dict[str, Any],
        *,
        country: str | None,
    ) -> CandidateDecision:
        ad = ad_from_detection(raw, country=country)
        return self.registry.consider(
            ad,
            creative_area=int(raw.get("creative_area") or 0),
        )

    def accept(self, decision: CandidateDecision) -> None:
        self.registry.commit(decision)

    def register_resolved(self, decision: CandidateDecision) -> bool:
        return self.registry.register_resolved(decision)

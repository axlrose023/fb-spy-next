from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Any


class RelevanceDecision(StrEnum):
    RELEVANT = "relevant"
    NOT_RELEVANT = "not_relevant"
    UNCERTAIN = "uncertain"


class RelevanceGate(StrEnum):
    ALLOW = "allow"
    DENY = "deny"
    HOLD = "hold"


@dataclass(frozen=True, slots=True)
class RelevanceResult:
    relevant: bool
    summary: dict[str, Any]
    raw_response: str | None = None
    source: str = "disabled"

    @property
    def decision(self) -> RelevanceDecision:
        value = str(self.summary.get("result") or "not_relevant")
        try:
            return RelevanceDecision(value)
        except ValueError:
            return RelevanceDecision.NOT_RELEVANT


def gate_for(decision: str) -> RelevanceGate:
    if decision == RelevanceDecision.RELEVANT:
        return RelevanceGate.ALLOW
    if decision == RelevanceDecision.NOT_RELEVANT:
        return RelevanceGate.DENY
    return RelevanceGate.HOLD

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class EvidenceCandidate:
    source: str = ""
    target: str = ""
    issue: str = ""

    @property
    def resolvable(self) -> bool:
        return bool(self.source and self.target and not self.issue)

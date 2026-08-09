from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class EngagementPolicy:
    reaction_rate: float = 0.65
    follow_rate: float = 0.20
    comment_every: int = 2
    max_reactions: int = 6
    max_follows: int = 2
    max_comments: int = 5
    min_interactions: int = 1

    @property
    def comments_enabled(self) -> bool:
        return self.comment_every > 0 and self.max_comments > 0


@dataclass(frozen=True, slots=True)
class EngagementPlan:
    reaction: bool
    comment: bool
    follow: bool
    landing_visit: bool

    def due_actions(self) -> tuple[str, ...]:
        return tuple(
            action
            for action, due in (
                ("reaction", self.reaction),
                ("comment", self.comment),
                ("follow", self.follow),
                ("landing_visit", self.landing_visit),
            )
            if due
        )

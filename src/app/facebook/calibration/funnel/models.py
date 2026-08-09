from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class OfferIdentity:
    first_name: str = ""
    last_name: str = ""
    email: str = ""
    phone: str = ""
    country_code: str = ""

    @property
    def full_name(self) -> str:
        return " ".join(part for part in (self.first_name, self.last_name) if part)

    @property
    def complete(self) -> bool:
        phone_digits = "".join(char for char in self.phone if char.isdigit())
        return bool(self.first_name and "@" in self.email and len(phone_digits) >= 7)


@dataclass(frozen=True, slots=True)
class OfferFunnelPolicy:
    enabled: bool = True
    direct_offer_fallback: bool = True
    browse_seconds: float = 45.0
    max_scrolls: int = 12
    quiz_max_questions: int = 10
    submit_mode: str = "disabled"
    submit_allow_domains: tuple[str, ...] = ()
    success_wait_seconds: float = 20.0
    max_retained_tabs: int = 6
    navigation_timeout_ms: int = 20_000

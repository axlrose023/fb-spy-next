from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class Profile:
    octo_profile_uuid: str
    label: str = ""
    expected_country: str | None = None
    enabled: bool = True
    no_country_filter: bool = False
    calibration_ads_json: list[str] = field(default_factory=list)
    quality_guard: bool = False
    failed_recovery_calibration_passes: int = 1

    @property
    def display_name(self) -> str:
        return self.label or self.octo_profile_uuid[:8]

    @property
    def storage_name(self) -> str:
        slug = "".join(
            char.lower() if char.isascii() and char.isalnum() else "_"
            for char in self.display_name
        )
        slug = "_".join(part for part in slug.split("_") if part) or "profile"
        return f"{slug[:40]}_{self.octo_profile_uuid[:8]}"

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> Profile:
        return cls(
            octo_profile_uuid=str(raw["octo_profile_uuid"]),
            label=str(raw.get("label") or ""),
            expected_country=raw.get("expected_country"),
            enabled=bool(raw.get("enabled", True)),
            no_country_filter=bool(raw.get("no_country_filter", False)),
            calibration_ads_json=[
                str(path) for path in raw.get("calibration_ads_json", [])
            ],
            quality_guard=bool(raw.get("quality_guard", False)),
            failed_recovery_calibration_passes=min(
                3,
                max(1, int(raw.get("failed_recovery_calibration_passes", 1))),
            ),
        )


@dataclass(frozen=True, slots=True)
class DiscoveredProfile:
    octo_profile_uuid: str
    label: str
    observed_country: str | None = None

    def configured(self, *, enabled: bool) -> Profile:
        return Profile(
            octo_profile_uuid=self.octo_profile_uuid,
            label=self.label,
            expected_country=self.observed_country,
            enabled=enabled,
        )


@dataclass(frozen=True, slots=True)
class DiscoveryResult:
    discovered: int
    added: int


@dataclass(frozen=True, slots=True)
class ProfileConnection:
    country: str | None = None
    ip: str | None = None

    def to_legacy_dict(self) -> dict[str, str]:
        result: dict[str, str] = {}
        if self.country:
            result["country"] = self.country
        if self.ip:
            result["ip"] = self.ip
        return result


@dataclass(frozen=True, slots=True)
class ActiveProfile:
    octo_profile_uuid: str
    label: str
    headless: bool
    ws_endpoint: str | None
    connection: ProfileConnection


@dataclass(frozen=True, slots=True)
class ProfileSession:
    ws_endpoint: str
    connection: ProfileConnection

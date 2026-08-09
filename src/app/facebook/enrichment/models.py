from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from .exceptions import RelevanceGateDenied


@dataclass(frozen=True, slots=True)
class RelevantAd:
    raw: dict[str, Any]

    @classmethod
    def from_raw(cls, raw: dict[str, Any]) -> RelevantAd:
        if raw.get("relevance_gate") != "allow":
            raise RelevanceGateDenied("Enrichment requires an allowed relevance gate")
        return cls(dict(raw))

    @property
    def target_key(self) -> str:
        raw = self.raw
        return str(
            raw.get("facebook_post_url")
            or raw.get("fb_ad_id")
            or "\x1f".join(
                str(raw.get(key) or "").casefold()
                for key in ("advertiser", "displayed_domain", "headline", "ad_text")
            )
        ).strip("\x1f")


@dataclass(frozen=True, slots=True)
class EnrichmentResult:
    ad: dict[str, Any]
    details: dict[str, Any]


@dataclass(frozen=True, slots=True)
class EnrichmentOptions:
    timeout_ms: int = 45_000
    locate_timeout_ms: int = 12_000
    wait_after_load: float = 2.0
    record_videos: bool = True
    video_max_seconds: float = 10.0
    resolve_landings: bool = True
    landing_archive_timeout: float = 20.0
    landing_archive_max_resources: int = 120

    @classmethod
    def from_namespace(cls, args: Any) -> EnrichmentOptions:
        return cls(
            timeout_ms=args.timeout_ms,
            locate_timeout_ms=args.locate_timeout_ms,
            wait_after_load=args.wait_after_load,
            record_videos=args.record_videos,
            video_max_seconds=args.video_max_seconds,
            resolve_landings=args.resolve_landings,
            landing_archive_timeout=args.landing_archive_timeout,
            landing_archive_max_resources=args.landing_archive_max_resources,
        )

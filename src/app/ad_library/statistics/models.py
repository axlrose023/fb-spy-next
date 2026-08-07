from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class Facet:
    value: str
    count: int


@dataclass(frozen=True, slots=True)
class AdStatistics:
    total_ads: int
    link_ads: int
    resolved_ads: int
    video_ads: int
    bad_screenshots: int
    by_type: tuple[Facet, ...]
    by_format: tuple[Facet, ...]
    by_vertical: tuple[Facet, ...]
    by_country: tuple[Facet, ...]
    by_language: tuple[Facet, ...]
    by_platform: tuple[Facet, ...]
    by_placement: tuple[Facet, ...]
    by_domain: tuple[Facet, ...]
    by_advertiser: tuple[Facet, ...]
    by_cta: tuple[Facet, ...]

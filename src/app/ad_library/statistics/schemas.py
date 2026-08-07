from __future__ import annotations

from pydantic import BaseModel

from .models import AdStatistics, Facet


class FacetItem(BaseModel):
    value: str
    count: int


class AdsStatsResponse(BaseModel):
    total_ads: int
    link_ads: int
    resolved_ads: int
    video_ads: int
    bad_screenshots: int
    by_type: list[FacetItem]
    by_format: list[FacetItem]
    by_vertical: list[FacetItem]
    by_country: list[FacetItem]
    by_language: list[FacetItem]
    by_platform: list[FacetItem]
    by_placement: list[FacetItem]
    by_domain: list[FacetItem]
    by_advertiser: list[FacetItem]
    by_cta: list[FacetItem]


def to_response(statistics: AdStatistics) -> AdsStatsResponse:
    return AdsStatsResponse(
        total_ads=statistics.total_ads,
        link_ads=statistics.link_ads,
        resolved_ads=statistics.resolved_ads,
        video_ads=statistics.video_ads,
        bad_screenshots=statistics.bad_screenshots,
        by_type=_to_facets(statistics.by_type),
        by_format=_to_facets(statistics.by_format),
        by_vertical=_to_facets(statistics.by_vertical),
        by_country=_to_facets(statistics.by_country),
        by_language=_to_facets(statistics.by_language),
        by_platform=_to_facets(statistics.by_platform),
        by_placement=_to_facets(statistics.by_placement),
        by_domain=_to_facets(statistics.by_domain),
        by_advertiser=_to_facets(statistics.by_advertiser),
        by_cta=_to_facets(statistics.by_cta),
    )


def _to_facets(items: tuple[Facet, ...]) -> list[FacetItem]:
    return [FacetItem(value=item.value, count=item.count) for item in items]

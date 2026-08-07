from pydantic import BaseModel


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

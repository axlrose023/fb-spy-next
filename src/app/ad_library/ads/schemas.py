from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from app.api.common.schema import Pagination, PaginationParams

from .models import AdCatalogPage, AdQuery, CatalogAd


class AdResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    run_id: UUID
    source_index: int | None = None
    advertiser: str
    ad_type: str
    format: str
    vertical: str | None = None
    country: str | None = None
    language: str | None = None
    platform: str
    placement: str
    cloaking: bool | None = None
    has_video: bool
    displayed_domain: str
    headline: str
    ad_text: str
    cta: str
    creative_img: str
    screenshot_url: str | None = None
    video_url: str | None = None
    landing_screenshot_url: str | None = None
    landing_archive_url: str | None = None
    screenshot_ok: bool | None = None
    screenshot_issue: str | None = None
    landing_full: str | None = None
    landing_clean: str | None = None
    fb_ad_id: str | None = None
    utm: dict[str, Any] = Field(default_factory=dict)
    captured_at: datetime | None = None
    created_at: datetime
    updated_at: datetime


class AdsPaginationResponse(Pagination[AdResponse]):
    model_config = ConfigDict(from_attributes=True)
    pass


class AdsPaginationParams(PaginationParams):
    run_id: UUID | None = None
    ad_type: list[str] | None = None
    format: str | None = None
    vertical: str | None = None
    country: str | None = None
    language: str | None = None
    platform: str | None = None
    placement: str | None = None
    cloaking: bool | None = None
    has_video: bool | None = None
    screenshot_ok: bool | None = None
    advertiser__search: str | None = None
    displayed_domain__search: str | None = None
    fb_ad_id: str | None = None
    has_landing: bool | None = None
    q: str | None = None
    order_by: str = "-captured_at"


def to_query(params: AdsPaginationParams) -> AdQuery:
    return AdQuery(
        page=params.page,
        page_size=params.page_size,
        run_id=params.run_id,
        ad_types=tuple(params.ad_type) if params.ad_type else None,
        format=params.format,
        vertical=params.vertical,
        country=params.country,
        language=params.language,
        platform=params.platform,
        placement=params.placement,
        cloaking=params.cloaking,
        has_video=params.has_video,
        screenshot_ok=params.screenshot_ok,
        advertiser_search=params.advertiser__search,
        displayed_domain_search=params.displayed_domain__search,
        fb_ad_id=params.fb_ad_id,
        has_landing=params.has_landing,
        search=params.q,
        order_by=params.order_by,
    )


def to_response(item: CatalogAd) -> AdResponse:
    response: AdResponse = AdResponse.model_validate(item.ad)
    updated: AdResponse = response.model_copy(
        update={
            "screenshot_url": item.media.screenshot_url,
            "video_url": item.media.video_url,
            "landing_screenshot_url": item.media.landing_screenshot_url,
            "landing_archive_url": item.media.landing_archive_url,
        }
    )
    return updated


def to_page_response(page: AdCatalogPage) -> AdsPaginationResponse:
    return AdsPaginationResponse(
        total=page.total,
        items=[to_response(item) for item in page.items],
        page=page.page,
        page_size=page.page_size,
    )

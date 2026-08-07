from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from app.api.common.schema import Pagination, PaginationParams


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
    utm: dict = Field(default_factory=dict)
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

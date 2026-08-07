from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any
from uuid import UUID


@dataclass(slots=True)
class Ad:
    id: UUID
    run_id: UUID
    source_index: int | None = None
    source_key: str | None = None
    advertiser: str = ""
    ad_type: str = "unknown"
    format: str = "image"
    vertical: str | None = None
    country: str | None = None
    language: str | None = None
    platform: str = "facebook"
    placement: str = "feed"
    cloaking: bool | None = None
    has_video: bool = False
    displayed_domain: str = ""
    headline: str = ""
    ad_text: str = ""
    cta: str = ""
    creative_img: str = ""
    video_path: str | None = None
    screenshot_path: str | None = None
    screenshot_ok: bool | None = None
    screenshot_issue: str | None = None
    landing_full: str | None = None
    landing_clean: str | None = None
    landing_screenshot_path: str | None = None
    landing_archive_path: str | None = None
    fb_ad_id: str | None = None
    utm: dict[str, Any] = field(default_factory=dict)
    captured_at: datetime | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None


@dataclass(frozen=True, slots=True)
class AdQuery:
    page: int = 1
    page_size: int = 10
    run_id: UUID | None = None
    ad_types: tuple[str, ...] | None = None
    format: str | None = None
    vertical: str | None = None
    country: str | None = None
    language: str | None = None
    platform: str | None = None
    placement: str | None = None
    cloaking: bool | None = None
    has_video: bool | None = None
    screenshot_ok: bool | None = None
    advertiser_search: str | None = None
    displayed_domain_search: str | None = None
    fb_ad_id: str | None = None
    has_landing: bool | None = None
    search: str | None = None
    order_by: str = "-captured_at"

    @property
    def offset(self) -> int:
        return (self.page - 1) * self.page_size


@dataclass(frozen=True, slots=True)
class AdPage:
    items: list[Ad]
    total: int
    page: int
    page_size: int


@dataclass(frozen=True, slots=True)
class AdMediaLinks:
    screenshot_url: str | None
    video_url: str | None
    landing_screenshot_url: str | None
    landing_archive_url: str | None


@dataclass(frozen=True, slots=True)
class CatalogAd:
    ad: Ad
    media: AdMediaLinks


@dataclass(frozen=True, slots=True)
class AdCatalogPage:
    items: list[CatalogAd]
    total: int
    page: int
    page_size: int

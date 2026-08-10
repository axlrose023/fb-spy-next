from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from app.facebook.timing import utc_now

from .deduplication import coarse_key_for, dedup_key_for


@dataclass(slots=True)
class CollectedAd:
    advertiser: str
    ad_type: str
    has_video: bool = False
    country: str | None = None
    displayed_domain: str = ""
    headline: str = ""
    ad_text: str = ""
    cta: str = ""
    cta_href: str = ""
    creative_img: str = ""
    video: str = ""
    screenshot: str = ""
    screenshot_ok: bool = True
    screenshot_issue: str = ""
    landing_full: str | None = None
    landing_clean: str | None = None
    landing_screenshot: str | None = None
    landing_archive: str | None = None
    fb_ad_id: str | None = None
    feed_element_id: str | None = None
    facebook_page_url: str | None = None
    facebook_post_url: str | None = None
    utm: dict[str, Any] = field(default_factory=dict)
    captured_at: str = field(default_factory=utc_now)

    def dedup_key(self) -> str:
        key: str = dedup_key_for(self)
        return key

    def coarse_key(self) -> str:
        key: str = coarse_key_for(self)
        return key


@dataclass(frozen=True, slots=True)
class CandidateDecision:
    ad: CollectedAd
    key: str
    coarse_key: str
    lazy_media: bool
    accepted: bool
    reason: str
    inherited_from: CollectedAd | None = None
    removed_keys: tuple[str, ...] = ()
    related_keys: tuple[str, ...] = ()

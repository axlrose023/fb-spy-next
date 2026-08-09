from __future__ import annotations

import re
from typing import Protocol
from urllib.parse import urlsplit


class AdIdentity(Protocol):
    advertiser: str
    displayed_domain: str
    headline: str
    ad_text: str
    cta: str
    creative_img: str
    fb_ad_id: str | None


def normalize_fingerprint_text(value: str) -> str:
    return re.sub(r"\s+", " ", value or "").strip().casefold()


def creative_identity(url: str) -> str:
    if not url:
        return ""
    try:
        parsed = urlsplit(url)
        return f"{parsed.netloc.casefold()}{parsed.path}"
    except ValueError:
        return url.split("?", 1)[0]


def dedup_key_for(ad: AdIdentity) -> str:
    if ad.fb_ad_id:
        return f"adid:{ad.fb_ad_id}"
    parts = (
        ad.advertiser,
        ad.displayed_domain,
        ad.headline,
        ad.ad_text,
        ad.cta,
        creative_identity(ad.creative_img),
    )
    return "creative:" + "\x1f".join(normalize_fingerprint_text(part) for part in parts)


def coarse_key_for(ad: AdIdentity) -> str:
    parts = (
        ad.advertiser,
        ad.displayed_domain,
        ad.headline,
        ad.ad_text,
        ad.cta,
    )
    return "text:" + "\x1f".join(normalize_fingerprint_text(part) for part in parts)


def is_lazy_video_image(
    url: str,
    *,
    has_video: bool,
    creative_area: int,
) -> bool:
    if not has_video or creative_area < 45_000 or not url:
        return False
    match = re.search(r"(?:^|[_=&])p(\d{2,4})x(\d{2,4})(?:[_&]|$)", url)
    return bool(match and max(int(match.group(1)), int(match.group(2))) <= 240)

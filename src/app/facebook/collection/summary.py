from __future__ import annotations

from .models import CollectedAd


def ad_summary(ads: dict[str, CollectedAd]) -> dict[str, object]:
    by_type: dict[str, int] = {}
    countries: dict[str, int] = {}
    domains: dict[str, int] = {}
    for ad in ads.values():
        by_type[ad.ad_type] = by_type.get(ad.ad_type, 0) + 1
        if ad.country:
            countries[ad.country] = countries.get(ad.country, 0) + 1
        domain = ad.landing_clean or ad.landing_full or ad.displayed_domain
        if domain:
            domains[domain] = domains.get(domain, 0) + 1
    resolved = [ad for ad in ads.values() if ad.landing_full or ad.landing_clean]
    screenshots = [ad for ad in ads.values() if ad.screenshot]
    return {
        "unique_ads": len(ads),
        "by_type": by_type,
        "countries": countries,
        "resolved_landings": len(resolved),
        "unique_landing_clean": len(
            {
                ad.landing_clean or ad.landing_full
                for ad in resolved
                if ad.landing_clean or ad.landing_full
            }
        ),
        "unique_fb_ad_ids": len({ad.fb_ad_id for ad in ads.values() if ad.fb_ad_id}),
        "unique_advertisers": len(
            {ad.advertiser for ad in ads.values() if ad.advertiser}
        ),
        "unique_domains": len(domains),
        "screenshot_attempted": len(screenshots),
        "screenshot_ok": sum(1 for ad in screenshots if ad.screenshot_ok is not False),
        "video_ads": sum(1 for ad in ads.values() if ad.has_video),
    }

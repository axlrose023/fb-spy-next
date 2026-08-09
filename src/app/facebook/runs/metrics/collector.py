from __future__ import annotations

from pathlib import Path

from .evidence import (
    clean_landing_key,
    count_by,
    counts,
    domain_key,
    domain_value,
    has_relevance,
    is_relevant,
)
from .loading import elapsed_from_timestamps, last_captured_at, load_ads, load_json
from .models import RunMetrics
from .normalization import (
    bool_or_none,
    clean,
    float_or_none,
    geo_matches,
    hourly_rate,
    int_or_none,
    normalize,
    per_100,
    safe_div,
)


def collect_run_metrics(
    run_dir: Path | str,
    *,
    expected_country: str | None = None,
    return_code: int | None = None,
    default_elapsed_seconds: float | None = None,
    default_requested_minutes: float | None = None,
    default_scrolls: int | None = None,
    calibration_targets_available: int | None = None,
) -> RunMetrics:
    run_path = Path(run_dir)
    ads = load_ads(run_path)
    meta = load_json(run_path / "run_meta.json", default={})
    summary = load_json(run_path / "summary.json", default={})

    started_at = clean(meta.get("started_at") or summary.get("started_at"))
    finished_at = clean(summary.get("finished_at")) or last_captured_at(ads)
    elapsed_seconds = float_or_none(summary.get("elapsed_seconds"))
    if elapsed_seconds is None:
        elapsed_seconds = elapsed_from_timestamps(started_at, finished_at)
    if elapsed_seconds is None:
        elapsed_seconds = default_elapsed_seconds

    requested_minutes = float_or_none(
        summary.get("requested_minutes") or summary.get("minutes")
    )
    if requested_minutes is None:
        requested_minutes = default_requested_minutes

    scrolls = int_or_none(summary.get("scrolls"))
    if scrolls is None:
        scrolls = default_scrolls
    refreshes = int_or_none(summary.get("refreshes"))
    captured_candidates = int_or_none(summary.get("captured_candidates"))
    duplicate_fb_ad_ids = int(int_or_none(summary.get("duplicate_fb_ad_ids")) or 0)
    stop_reason = clean(summary.get("stop_reason"))

    profile_country = clean(meta.get("profile_country"))
    country_target = expected_country or profile_country
    by_type = count_by(ads, "ad_type")
    resolved_ads = [
        ad for ad in ads if clean(ad.get("landing_full") or ad.get("landing_clean"))
    ]
    domains = [domain_key(domain_value(ad)) for ad in ads]
    domains = [domain for domain in domains if domain]
    domain_counts = counts(domains)
    screenshot_attempted = sum(1 for ad in ads if clean(ad.get("screenshot")))
    screenshot_ok = sum(
        1
        for ad in ads
        if clean(ad.get("screenshot")) and ad.get("screenshot_ok") is not False
    )
    countries = [
        clean(ad.get("country")) for ad in ads if clean(ad.get("country"))
    ]
    country_match_rate = None
    if countries and country_target:
        normalized_target = normalize(country_target)
        country_match_rate = sum(
            1 for country in countries if normalize(country) == normalized_target
        ) / len(countries)

    relevance_classified_ads = sum(1 for ad in ads if has_relevance(ad))
    relevance_coverage = safe_div(relevance_classified_ads, len(ads))
    relevance_known = (
        relevance_classified_ads > 0
        and relevance_coverage is not None
        and relevance_coverage >= 0.90
    )
    relevant_ads = None
    relevant_rate = None
    if relevance_known:
        relevant_ads = sum(1 for ad in ads if is_relevant(ad))
        relevant_rate = safe_div(relevant_ads, relevance_classified_ads)

    target_source = "relevance" if relevance_known else "resolved_landings"
    target_ads = relevant_ads if relevant_ads is not None else len(resolved_ads)
    hours = safe_div(elapsed_seconds, 3600.0)
    profile_uuid = clean(meta.get("octo_profile_uuid"))
    profile_expected = expected_country or clean(meta.get("expected_country"))

    return RunMetrics(
        run_dir=str(run_path),
        collector_metric_version=int_or_none(meta.get("collector_metric_version")) or 1,
        profile_uuid=profile_uuid,
        profile_country=profile_country,
        expected_country=profile_expected,
        octo_ip=clean(
            meta.get("octo_ip") or (meta.get("connection_data") or {}).get("ip")
        ),
        octo_headless=(
            bool_or_none(meta.get("octo_headless"))
            if "octo_headless" in meta
            else False
        ),
        started_at=started_at,
        finished_at=finished_at,
        return_code=return_code,
        stop_reason=stop_reason,
        elapsed_seconds=elapsed_seconds,
        requested_minutes=requested_minutes,
        scrolls=scrolls,
        refreshes=refreshes,
        captured_candidates=captured_candidates,
        duplicate_fb_ad_ids=duplicate_fb_ad_ids,
        ads_total=len(ads),
        link_ads=by_type.get("link", 0),
        video_ads=by_type.get("video", 0),
        in_facebook_ads=by_type.get("in_facebook", 0),
        resolved_landings=len(resolved_ads),
        unique_landing_clean=len(
            {
                clean_landing_key(ad.get("landing_clean") or ad.get("landing_full"))
                for ad in resolved_ads
                if clean_landing_key(
                    ad.get("landing_clean") or ad.get("landing_full")
                )
            }
        ),
        unique_fb_ad_ids=len(
            {clean(ad.get("fb_ad_id")) for ad in ads if clean(ad.get("fb_ad_id"))}
        ),
        unique_advertisers=len(
            {
                normalize(clean(ad.get("advertiser")))
                for ad in ads
                if clean(ad.get("advertiser"))
            }
        ),
        unique_domains=len(set(domains)),
        top_domain_share=(
            max(domain_counts.values()) / len(domains) if domains else None
        ),
        screenshot_attempted=screenshot_attempted,
        screenshot_ok=screenshot_ok,
        screenshot_ok_rate=safe_div(screenshot_ok, screenshot_attempted),
        country_match_rate=country_match_rate,
        geo_observed=bool(profile_country),
        geo_match=geo_matches(profile_expected, profile_country),
        relevance_known=relevance_known,
        relevance_classified_ads=relevance_classified_ads,
        relevance_coverage=relevance_coverage,
        relevant_ads=relevant_ads,
        relevant_rate=relevant_rate,
        target_source=target_source,
        target_ads=target_ads,
        ads_per_hour=hourly_rate(len(ads), hours),
        target_per_hour=hourly_rate(target_ads, hours),
        resolved_per_hour=hourly_rate(len(resolved_ads), hours),
        ads_per_100_scrolls=per_100(len(ads), scrolls),
        target_per_100_scrolls=per_100(target_ads, scrolls),
        resolved_per_100_scrolls=per_100(len(resolved_ads), scrolls),
        calibration_targets_available=calibration_targets_available,
    )

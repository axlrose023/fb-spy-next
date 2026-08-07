import json
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

from app.services.facebook.calibration import (
    CalibrationTarget,
    append_event,
    load_engagement_targets_from_ads_json,
    load_saved_facebook_targets_from_ads_json,
    load_targets_from_ads_json,
    quarantined_facebook_post_urls,
    record_facebook_post_target_result,
    rotate_calibration_targets,
    select_calibration_targets,
    write_targets,
)
from app.services.facebook_calibrator import _should_stop_after_target_result


def test_manual_batch_can_continue_after_one_transient_navigation_error() -> None:
    result = {
        "infrastructure_error": True,
        "transient_navigation_error": True,
    }

    assert not _should_stop_after_target_result(
        result,
        SimpleNamespace(continue_on_target_navigation_error=True),
    )
    assert _should_stop_after_target_result(
        result,
        SimpleNamespace(continue_on_target_navigation_error=False),
    )


def test_manual_batch_still_stops_when_browser_context_closed() -> None:
    result = {
        "infrastructure_error": True,
        "transient_navigation_error": True,
        "browser_context_closed": True,
    }

    assert _should_stop_after_target_result(
        result,
        SimpleNamespace(continue_on_target_navigation_error=True),
    )


def test_select_calibration_targets_filters_country_and_deduplicates() -> None:
    raw_ads = [
        {
            "advertiser": "A",
            "country": "France",
            "landing_full": "https://example.com/a?fbclid=1",
            "landing_clean": "https://example.com/a",
            "fb_ad_id": "111",
            "captured_at": "2026-07-01T10:00:00+00:00",
        },
        {
            "advertiser": "A duplicate",
            "country": "France",
            "landing_full": "https://example.com/a?fbclid=2",
            "landing_clean": "https://example.com/a",
            "captured_at": "2026-07-01T11:00:00+00:00",
        },
        {
            "advertiser": "B",
            "country": "Germany",
            "landing_full": "https://example.de/b",
            "landing_clean": "https://example.de/b",
        },
        {
            "advertiser": "No landing",
            "country": "France",
            "creative_img": "https://cdn.example/image.jpg",
        },
    ]

    targets = select_calibration_targets(raw_ads, country="France", limit=10)

    assert len(targets) == 1
    assert targets[0].advertiser == "A"
    assert targets[0].url == "https://example.com/a?fbclid=1"


def test_select_calibration_targets_applies_domain_limit_then_backfills() -> None:
    raw_ads = [
        {
            "advertiser": f"Same {index}",
            "country": "France",
            "landing_full": f"https://same.example/path-{index}",
            "landing_clean": f"https://same.example/path-{index}",
            "captured_at": f"2026-07-01T10:0{index}:00+00:00",
        }
        for index in range(3)
    ]
    raw_ads.append(
        {
            "advertiser": "Other",
            "country": "France",
            "landing_full": "https://other.example/path",
            "landing_clean": "https://other.example/path",
            "captured_at": "2026-07-01T10:10:00+00:00",
        }
    )

    targets = select_calibration_targets(
        raw_ads,
        country="France",
        limit=3,
        max_per_domain=1,
    )

    assert [target.domain_key for target in targets] == [
        "other.example",
        "same.example",
        "same.example",
    ]


def test_distinct_facebook_ads_can_share_a_landing() -> None:
    raw_ads = [
        {
            "fb_ad_id": "111",
            "landing_full": "https://same.example/click?ad_id=111",
            "landing_clean": "https://same.example/click",
        },
        {
            "fb_ad_id": "222",
            "landing_full": "https://same.example/click?ad_id=222",
            "landing_clean": "https://same.example/click",
        },
    ]

    targets = select_calibration_targets(raw_ads, limit=10)

    assert [target.fb_ad_id for target in targets] == ["111", "222"]


def test_load_targets_from_ads_json_and_write_artifacts(tmp_path) -> None:
    ads_json = tmp_path / "ads.json"
    ads_json.write_text(
        json.dumps(
            [
                {
                    "advertiser": "Json Brand",
                    "country": "France",
                    "landing_full": "https://json.example/full",
                    "landing_clean": "https://json.example/",
                }
            ],
        ),
        encoding="utf-8",
    )

    targets = load_targets_from_ads_json([ads_json], country="France")
    targets_path = tmp_path / "targets.json"
    events_path = tmp_path / "events.jsonl"
    write_targets(targets_path, targets)
    append_event(events_path, {"kind": "test", "target": targets[0]})

    saved_targets = json.loads(targets_path.read_text(encoding="utf-8"))
    saved_events = events_path.read_text(encoding="utf-8").splitlines()
    assert saved_targets[0]["advertiser"] == "Json Brand"
    assert saved_targets[0]["source"] == str(ads_json.resolve())
    assert len(saved_events) == 1
    assert targets_path.stat().st_mode & 0o777 == 0o600
    assert events_path.stat().st_mode & 0o777 == 0o600


def test_load_targets_can_require_explicit_relevance(tmp_path) -> None:
    ads_json = tmp_path / "ads.json"
    ads_json.write_text(
        json.dumps([
            {
                "landing_full": "https://accepted.example",
                "relevance": {"result": "relevant"},
            },
            {
                "landing_full": "https://rejected.example",
                "relevance": {"result": "not_relevant"},
            },
            {"landing_full": "https://unknown.example"},
        ]),
        encoding="utf-8",
    )

    targets = load_targets_from_ads_json(
        [ads_json],
        require_relevant=True,
    )

    assert [target.url for target in targets] == ["https://accepted.example"]


def test_engagement_targets_include_relevant_ads_without_landings(tmp_path) -> None:
    ads_json = tmp_path / "ads.relevant.json"
    ads_json.write_text(
        json.dumps([
            {
                "advertiser": "Saved advertiser",
                "displayed_domain": "relevant.example",
                "headline": "Saved headline",
                "feed_element_id": "fbspy-current",
                "relevance": {"result": "relevant"},
            },
            {
                "advertiser": "Rejected advertiser",
                "relevance": {"result": "not_relevant"},
            },
        ]),
        encoding="utf-8",
    )

    targets = load_engagement_targets_from_ads_json([ads_json])

    assert len(targets) == 1
    assert targets[0].url == ""
    assert targets[0].feed_element_id == "fbspy-current"


def test_saved_facebook_targets_require_relevant_direct_post_urls(tmp_path) -> None:
    ads_json = tmp_path / "ads.relevant.json"
    ads_json.write_text(
        json.dumps([
            {
                "advertiser": "Direct relevant",
                "country": "Spain",
                "fb_ad_id": "ad-1",
                "facebook_post_url": "https://m.facebook.com/100/posts/200",
                "landing_full": "https://landing.example/one",
                "landing_clean": "https://landing.example/one",
                "cta": "Learn more",
                "relevance": {"result": "relevant"},
            },
            {
                "advertiser": "No permalink",
                "country": "Spain",
                "landing_full": "https://landing.example/two",
                "relevance": {"result": "relevant"},
            },
            {
                "advertiser": "Not relevant",
                "country": "Spain",
                "facebook_post_url": "https://m.facebook.com/300/posts/400",
                "relevance": {"result": "not_relevant"},
            },
            {
                "advertiser": "Story relevant",
                "country": "Spain",
                "facebook_post_url": (
                    "https://m.facebook.com/story.php?story_fbid=600&id=500"
                ),
                "relevance": {"result": "relevant"},
            },
        ]),
        encoding="utf-8",
    )

    targets = load_saved_facebook_targets_from_ads_json(
        [ads_json],
        country="Spain",
    )

    assert len(targets) == 2
    assert targets[0].url == "https://m.facebook.com/100/posts/200"
    assert targets[0].landing_clean == "https://landing.example/one"
    assert targets[0].cta == "Learn more"
    assert targets[1].url.endswith("story.php?story_fbid=600&id=500")


def test_saved_facebook_targets_skip_quarantined_urls(tmp_path) -> None:
    post_url = "https://m.facebook.com/100/posts/200"
    ads_json = tmp_path / "ads.relevant.json"
    ads_json.write_text(
        json.dumps([
            {
                "country": "Spain",
                "facebook_post_url": post_url,
                "relevance": {"result": "relevant"},
            }
        ]),
        encoding="utf-8",
    )

    targets = load_saved_facebook_targets_from_ads_json(
        [ads_json],
        country="Spain",
        excluded_urls={post_url},
    )

    assert targets == []


def test_funnel_targets_keep_full_offer_when_mobile_post_is_unavailable(
    tmp_path,
) -> None:
    ads_json = tmp_path / "ads.relevant.json"
    ads_json.write_text(
        json.dumps([
            {
                "advertiser": "Relevant offer",
                "country": "Spain",
                "fb_ad_id": "1202475030516302598",
                "landing_full": (
                    "https://offer.example/click?ad_id=1202475030516302598"
                    "&campaign_id=1202475030517202598"
                ),
                "landing_clean": "https://offer.example/click",
                "relevance": {"result": "relevant"},
            }
        ]),
        encoding="utf-8",
    )

    targets = load_saved_facebook_targets_from_ads_json(
        [ads_json],
        country="Spain",
        include_direct_offers=True,
    )

    assert len(targets) == 1
    assert targets[0].facebook_post_url is None
    assert "campaign_id=" in targets[0].landing_full
    assert targets[0].url == targets[0].landing_full


def test_funnel_target_can_use_saved_cta_href(tmp_path) -> None:
    ads_json = tmp_path / "ads.relevant.json"
    ads_json.write_text(
        json.dumps([
            {
                "country": "Canada",
                "fb_ad_id": "cta-only",
                "cta_href": "https://offer.example/click?campaign=authorized-test",
                "relevance": {"result": "relevant"},
            }
        ]),
        encoding="utf-8",
    )

    targets = load_saved_facebook_targets_from_ads_json(
        [ads_json],
        country="Canada",
        include_direct_offers=True,
    )

    assert len(targets) == 1
    assert targets[0].url == "https://offer.example/click?campaign=authorized-test"
    assert targets[0].cta_href == targets[0].url


def test_target_health_quarantines_repeated_missing_post_and_resets_on_success(
    tmp_path,
) -> None:
    health_path = tmp_path / "target_health.json"
    post_url = "https://m.facebook.com/100/posts/200"
    missing = {
        "url": post_url,
        "ok": False,
        "match": {"status": "post_not_found"},
    }
    started_at = datetime(2026, 7, 21, 12, tzinfo=UTC)

    record_facebook_post_target_result(health_path, missing, now=started_at)
    assert quarantined_facebook_post_urls(health_path, now=started_at) == set()

    record_facebook_post_target_result(
        health_path,
        missing,
        now=started_at + timedelta(minutes=1),
    )
    assert quarantined_facebook_post_urls(
        health_path,
        now=started_at + timedelta(minutes=1),
    ) == {post_url}

    record_facebook_post_target_result(
        health_path,
        {"url": post_url, "ok": True},
        now=started_at + timedelta(minutes=2),
    )
    assert quarantined_facebook_post_urls(
        health_path,
        now=started_at + timedelta(minutes=2),
    ) == set()


def test_rotate_calibration_targets_wraps_without_dropping_targets() -> None:
    targets = [
        CalibrationTarget(url=f"https://example.com/{advertiser}", advertiser=advertiser)
        for advertiser in ["A", "B", "C", "D", "E"]
    ]

    rotated = rotate_calibration_targets(targets, 3)

    assert [target.advertiser for target in rotated] == ["D", "E", "A", "B", "C"]

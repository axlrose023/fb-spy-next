import pytest

from app.facebook.collection import CollectedAd, ad_summary

pytestmark = pytest.mark.unit


def test_summary_preserves_collector_metric_shape() -> None:
    ads = {
        "one": CollectedAd(
            advertiser="Publisher",
            ad_type="link",
            country="Canada",
            displayed_domain="offer.test",
            landing_clean="https://offer.test/path",
            fb_ad_id="1",
            screenshot="screens/one.png",
            screenshot_ok=True,
        ),
        "two": CollectedAd(
            advertiser="Publisher",
            ad_type="video",
            has_video=True,
            country="Canada",
            displayed_domain="video.test",
            screenshot="screens/two.png",
            screenshot_ok=False,
        ),
    }

    assert ad_summary(ads) == {
        "unique_ads": 2,
        "by_type": {"link": 1, "video": 1},
        "countries": {"Canada": 2},
        "resolved_landings": 1,
        "unique_landing_clean": 1,
        "unique_fb_ad_ids": 1,
        "unique_advertisers": 1,
        "unique_domains": 2,
        "screenshot_attempted": 2,
        "screenshot_ok": 1,
        "video_ads": 1,
    }
